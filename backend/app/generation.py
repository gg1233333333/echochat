import asyncio
import copy
import json
import logging
import time
from dataclasses import dataclass, field

import httpx
from sqlalchemy import delete, select

from app.agent import AgentExecution
from app.errors import AppError
from app.models import Attachment, Message, new_id, now
from app.options import ROLES
from app.service import ChatService, message_data, validate_generation
from app.tools import ToolRuntime

logger = logging.getLogger("echochat.generations")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)


def encode_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@dataclass
class Generation:
    request_id: str
    conversation_id: str
    message_id: str
    started: dict
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    finishing: bool = False


class GenerationService:
    def __init__(self, chats: ChatService, client: httpx.AsyncClient):
        self.chats = chats
        self.client = client
        self.api_key: str | None = None
        self.active: Generation | None = None
        self.accepted_request_ids: set[str] = set()

    def check_context_mutable(self, conversation_id: str):
        if self.active and self.active.conversation_id == conversation_id:
            raise AppError(409, "GENERATION_BUSY", "请先停止当前生成再修改上下文。")

    @staticmethod
    def disconnect(generation: Generation | dict):
        if (
            isinstance(generation, Generation)
            and generation.task
            and not generation.done.is_set()
            and not generation.task.cancelling()
            and not generation.finishing
        ):
            generation.task.cancel()

    async def cancel_active(self):
        active = self.active
        if active:
            await active.ready.wait()
            if (
                active.task
                and not active.task.done()
                and not active.task.cancelling()
                and not active.finishing
            ):
                active.task.cancel()
            await active.done.wait()

    async def cancel(self, request_id: str):
        async with self.chats.lock:
            active = self.active
            if active and active.request_id == request_id:
                await self.cancel_active()
            async with self.chats.db.sessions() as session:
                message = await session.scalar(
                    select(Message).where(Message.request_id == request_id)
                )
                if message is None:
                    raise AppError(404, "GENERATION_NOT_FOUND", "生成请求不存在。")
                return {"message": message_data(message)}

    async def replay(self, message: Message, session):
        conversation = await self.chats.require_conversation(session, message.conversation_id)
        user = (
            await session.get(Message, message.related_user_message_id)
            if message.related_user_message_id
            else None
        )
        return {
            "request_id": message.request_id,
            "conversation_id": message.conversation_id,
            "message": message_data(message),
            "user_message": message_data(user) if user else None,
            "conversation": await self.chats.conversation_data(session, conversation),
        }

    async def prepare(
        self,
        *,
        request_id: str,
        mode: str,
        conversation_id: str | None = None,
        text: str = "",
        attachments: list[dict] | None = None,
        regenerate_id: str | None = None,
        agent_enabled: bool = False,
    ) -> Generation | dict:
        validate_generation(mode, request_id)
        attachments = attachments or []
        async with self.chats.lock:
            async with self.chats.db.sessions.begin() as session:
                existing = await session.scalar(
                    select(Message).where(Message.request_id == request_id)
                )
                if existing:
                    if existing.regenerated_from_id != regenerate_id:
                        raise AppError(409, "REQUEST_ID_REUSED", "请求 ID 已用于其他操作。")
                    if conversation_id and existing.conversation_id != conversation_id:
                        raise AppError(409, "REQUEST_ID_REUSED", "请求 ID 已用于其他会话。")
                    if existing.status == "generating":
                        raise AppError(
                            409, "REQUEST_IN_PROGRESS", "此请求仍在生成，请查询消息状态。"
                        )
                    return await self.replay(existing, session)
                if request_id in self.accepted_request_ids:
                    raise AppError(409, "REQUEST_REMOVED", "该请求的消息已删除，请发起新的请求。")
                if self.active is not None:
                    raise AppError(409, "GENERATION_BUSY", "已有回复正在生成，请先等待或停止。")
                if not self.api_key:
                    raise AppError(400, "API_KEY_REQUIRED", "请先在页面配置 DeepSeek API Key。")
                if regenerate_id:
                    target = await self.chats.require_message(session, regenerate_id)
                    if target.role != "assistant" or not target.related_user_message_id:
                        raise AppError(409, "CANNOT_REGENERATE", "关联提问不存在，无法重新生成。")
                    user = await session.get(Message, target.related_user_message_id)
                    if (
                        user is None
                        or user.role != "user"
                        or user.conversation_id != target.conversation_id
                        or user.seq >= target.seq
                        or target.role_id not in ROLES
                        or not target.context_segment
                        or user.context_segment != target.context_segment
                    ):
                        raise AppError(409, "UNKNOWN_CONTEXT", "无法确认原始上下文，不能重新生成。")
                    conversation = await self.chats.require_conversation(
                        session, target.conversation_id
                    )
                    role_id, segment = target.role_id, target.context_segment
                    context = await self.chats.build_context(
                        session, conversation.id, role_id, segment, user.seq
                    )
                    removed_requests = await session.scalars(
                        select(Message.request_id).where(
                            Message.conversation_id == conversation.id,
                            Message.seq >= target.seq,
                            Message.request_id.is_not(None),
                        )
                    )
                    self.accepted_request_ids.update(removed_requests)
                    await session.execute(
                        delete(Message).where(
                            Message.conversation_id == conversation.id, Message.seq >= target.seq
                        )
                    )
                    conversation.current_role_id = role_id
                    conversation.context_segment = segment
                else:
                    if not text.strip() and not attachments:
                        raise AppError(422, "EMPTY_MESSAGE", "请输入消息或选择附件。")
                    if len(text) > 100_000:
                        raise AppError(413, "MESSAGE_TOO_LARGE", "单条输入最多 100000 字符。")
                    conversation = await self.chats.require_conversation(session, conversation_id)
                    role_id, segment = conversation.current_role_id, conversation.context_segment
                    self.chats.name_conversation(
                        conversation, text, [item["name"] for item in attachments]
                    )
                    user = Message(
                        id=new_id(),
                        conversation_id=conversation.id,
                        seq=conversation.next_seq,
                        role="user",
                        content=text.strip(),
                        role_id=role_id,
                        context_segment=segment,
                        mode=mode,
                        status="completed",
                        attachments=[Attachment(**item) for item in attachments],
                        artifacts=[],
                    )
                    conversation.next_seq += 1
                    session.add(user)
                    await session.flush()
                    context = await self.chats.build_context(
                        session, conversation.id, role_id, segment
                    )
                assistant = Message(
                    id=new_id(),
                    conversation_id=conversation.id,
                    seq=conversation.next_seq,
                    role="assistant",
                    content="",
                    role_id=role_id,
                    context_segment=segment,
                    mode=mode,
                    related_user_message_id=user.id,
                    request_id=request_id,
                    regenerated_from_id=regenerate_id,
                    status="generating",
                    attachments=[],
                    artifacts=[],
                    agent_steps=[],
                )
                conversation.next_seq += 1
                conversation.updated_at = now()
                session.add(assistant)
                await session.flush()
                started = {
                    "request_id": request_id,
                    "conversation_id": conversation.id,
                    "user_message": message_data(user),
                    "assistant_message": message_data(assistant),
                    "conversation": await self.chats.conversation_data(session, conversation),
                }
            active = Generation(request_id, conversation.id, assistant.id, started)
            self.accepted_request_ids.add(request_id)
            self.active = active
            active.task = asyncio.create_task(
                self.run(
                    active,
                    context,
                    mode,
                    self.api_key,
                    agent_enabled,
                    assistant.context_segment,
                    assistant.seq,
                ),
                name=f"generation-{request_id}",
            )
            await active.ready.wait()
            return active

    async def persist(self, active: Generation, content: str, **changes):
        async with self.chats.db.sessions.begin() as session:
            message = await session.get(Message, active.message_id)
            if message is None:
                return None
            message.content = content
            for key, value in changes.items():
                setattr(message, key, copy.deepcopy(value) if key == "agent_steps" else value)
            await session.flush()
            return message_data(message)

    async def final_data(self, active: Generation, content: str, **changes):
        message = await self.persist(active, content, **changes)
        async with self.chats.db.sessions() as session:
            conversation = await self.chats.require_conversation(session, active.conversation_id)
            return {
                "request_id": active.request_id,
                "conversation_id": active.conversation_id,
                "message": message,
                "conversation": await self.chats.conversation_data(session, conversation),
            }

    async def run(
        self,
        active: Generation,
        context: list[dict],
        mode: str,
        api_key: str,
        agent_enabled: bool,
        segment: str,
        seq: int,
    ):
        active.ready.set()
        started = time.monotonic()
        status, error_code, error_message = "completed", None, None

        async def emit(kind, data):
            await active.queue.put(
                (
                    kind,
                    {
                        "request_id": active.request_id,
                        "conversation_id": active.conversation_id,
                        "message_id": active.message_id,
                        **data,
                    },
                )
            )

        async def save(content, **changes):
            return await self.persist(active, content, **changes)

        execution = AgentExecution(
            ToolRuntime(
                self.chats.db, self.client, active.conversation_id, active.message_id, segment, seq
            ),
            emit,
            save,
            self.upstream_error,
            mode,
            api_key,
            agent_enabled,
        )
        try:
            await execution.run(context)
        except asyncio.CancelledError:
            status = "cancelled"
        except AppError as error:
            status, error_code, error_message = "failed", error.code, error.message
        except httpx.TimeoutException:
            status, error_code, error_message = (
                "failed",
                "UPSTREAM_TIMEOUT",
                "模型请求超时，请重试。",
            )
        except httpx.HTTPError:
            status, error_code, error_message = "failed", "UPSTREAM_NETWORK", "无法连接模型服务。"
        except TimeoutError:
            status, error_code, error_message = (
                "failed",
                "AGENT_TIMEOUT",
                "任务超过 5 分钟，已停止。",
            )
        except Exception as error:
            logger.error(
                "generation failed request_id=%s exception=%s",
                active.request_id,
                type(error).__name__,
            )
            status, error_code, error_message = (
                "failed",
                "GENERATION_ERROR",
                "生成失败，请稍后重试。",
            )
        active.finishing = True
        execution.interrupt_tools()
        try:
            final = await self.final_data(
                active,
                execution.content,
                reasoning_content=execution.reasoning,
                agent_steps=execution.steps,
                status=status,
                error_code=error_code,
                error_message=error_message,
                finish_reason=execution.finish_reason,
            )
            if status == "failed":
                await active.queue.put(
                    (
                        "error",
                        {
                            **final,
                            "code": error_code,
                            "message_text": error_message,
                        },
                    )
                )
            else:
                await active.queue.put(("done", final))
        except Exception:
            logger.error("generation persistence failed request_id=%s", active.request_id)
            await active.queue.put(
                (
                    "error",
                    {
                        "request_id": active.request_id,
                        "conversation_id": active.conversation_id,
                        "message": None,
                        "code": "PERSISTENCE_ERROR",
                        "message_text": "保存生成结果失败，请刷新确认消息状态。",
                    },
                )
            )
        finally:
            logger.info(
                "generation request_id=%s status=%s error=%s elapsed=%.2f",
                active.request_id,
                status,
                error_code,
                time.monotonic() - started,
            )
            if self.active is active:
                self.active = None
            active.done.set()
            await active.queue.put(None)

    @staticmethod
    def upstream_error(response: httpx.Response):
        mapping = {
            401: ("INVALID_API_KEY", "API Key 无效，请重新配置。"),
            402: ("INSUFFICIENT_BALANCE", "DeepSeek 账户余额不足。"),
            429: ("UPSTREAM_RATE_LIMIT", "模型服务请求过于频繁，请稍后重试。"),
            503: ("UPSTREAM_UNAVAILABLE", "模型服务暂不可用，请稍后重试。"),
        }
        if response.status_code == 400:
            try:
                error = response.json().get("error", {})
                description = str(error.get("code", "")) + str(error.get("message", ""))
                if "context" in description.lower() or "token" in description.lower():
                    return AppError(
                        400, "CONTEXT_TOO_LONG", "当前上下文超过模型限制，请开启新对话。"
                    )
            except (ValueError, AttributeError):
                pass
        code, message = mapping.get(
            response.status_code, ("UPSTREAM_REJECTED", "模型服务拒绝了请求，请稍后重试。")
        )
        return AppError(502, code, message)

    async def stream(self, generation: Generation | dict):
        if isinstance(generation, dict):
            yield encode_event(
                "started",
                {
                    **generation,
                    "assistant_message": generation["message"],
                },
            )
            yield encode_event("done", generation)
            return
        try:
            yield encode_event("started", generation.started)
            while True:
                try:
                    item = await asyncio.wait_for(generation.queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    break
                yield encode_event(*item)
        finally:
            # The producer owns persistence after the HTTP stream disconnects.
            self.disconnect(generation)
