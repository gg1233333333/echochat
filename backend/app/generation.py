import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

import httpx
from sqlalchemy import delete, select

from app.errors import AppError
from app.models import Attachment, Message, new_id, now
from app.options import MODES, ROLES
from app.service import ChatService, message_data, validate_generation

logger = logging.getLogger("echochat.generations")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)
UPSTREAM_URL = "https://api.deepseek.com/v1/chat/completions"


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
                self.run(active, context, mode, self.api_key), name=f"generation-{request_id}"
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
                setattr(message, key, value)
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

    async def run(self, active: Generation, context: list[dict], mode: str, api_key: str):
        active.ready.set()
        content = ""
        reasoning_content = ""
        finish_reason = None
        started = time.monotonic()
        last_saved = started
        status, error_code, error_message = "completed", None, None
        try:
            payload = {"model": "deepseek-flash", "messages": context, "stream": True}
            payload.update(MODES[mode]["request"])
            async with self.client.stream(
                "POST",
                UPSTREAM_URL,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            ) as response:
                if response.is_error:
                    await response.aread()
                    raise self.upstream_error(response)
                data_lines = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                    elif not line and data_lines:
                        data = "\n".join(data_lines)
                        data_lines = []
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            raise AppError(
                                502, "INVALID_UPSTREAM_STREAM", "模型返回了无效的数据流。"
                            ) from None
                        if "error" in chunk:
                            raise AppError(502, "UPSTREAM_ERROR", "模型服务在生成期间返回错误。")
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("delta", {})
                        answer_delta = delta.get("content")
                        reasoning_delta = delta.get("reasoning_content")
                        if any(
                            value is not None and not isinstance(value, str)
                            for value in (answer_delta, reasoning_delta)
                        ):
                            raise AppError(502, "INVALID_UPSTREAM_STREAM", "模型返回了无效的正文。")
                        answer_delta = answer_delta or ""
                        reasoning_delta = reasoning_delta or ""
                        if answer_delta or reasoning_delta:
                            content += answer_delta
                            reasoning_content += reasoning_delta
                            await active.queue.put(
                                (
                                    "delta",
                                    {
                                        "request_id": active.request_id,
                                        "conversation_id": active.conversation_id,
                                        "message_id": active.message_id,
                                        "content": answer_delta,
                                        "reasoning_content": reasoning_delta,
                                    },
                                )
                            )
                        finish_reason = choice.get("finish_reason") or finish_reason
                        if time.monotonic() - last_saved >= 1:
                            await self.persist(active, content, reasoning_content=reasoning_content)
                            last_saved = time.monotonic()
                if not finish_reason:
                    raise AppError(
                        502, "UPSTREAM_DISCONNECTED", "模型连接在完成前中断，请重新生成。"
                    )
                if finish_reason in ("aborted", "insufficient_system_resource", "content_filter"):
                    raise AppError(502, "UPSTREAM_INCOMPLETE", "模型未能完成回复，请查看完成原因。")
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
        try:
            final = await self.final_data(
                active,
                content,
                reasoning_content=reasoning_content,
                status=status,
                error_code=error_code,
                error_message=error_message,
                finish_reason=finish_reason,
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
