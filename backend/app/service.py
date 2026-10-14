import asyncio
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Database
from app.errors import AppError
from app.models import Attachment, Conversation, Message, new_id, now
from app.options import MODES, ROLES
from app.text import plain_preview


def attachment_data(attachment: Attachment) -> dict:
    fields = ("id", "name", "size", "mime", "extracted_text", "status", "note", "truncated")
    return {field: getattr(attachment, field) for field in fields}


def message_data(message: Message) -> dict:
    fields = (
        "id",
        "conversation_id",
        "seq",
        "role",
        "content",
        "reasoning_content",
        "role_id",
        "context_segment",
        "mode",
        "related_user_message_id",
        "request_id",
        "status",
        "error_code",
        "error_message",
        "finish_reason",
        "created_at",
    )
    return {
        **{field: getattr(message, field) for field in fields},
        "attachments": [attachment_data(item) for item in message.attachments],
    }


def validate_role(role_id: str):
    if role_id not in ROLES:
        raise AppError(422, "INVALID_ROLE", "不支持的助手角色。")


def validate_generation(mode: str, request_id: str):
    if mode not in MODES:
        raise AppError(422, "INVALID_MODE", "不支持的思考模式。")
    try:
        if str(UUID(request_id)) != request_id:
            raise ValueError()
    except (ValueError, AttributeError):
        raise AppError(422, "INVALID_REQUEST_ID", "请求 ID 必须是标准 UUID。") from None


class ChatService:
    def __init__(self, database: Database):
        self.db = database
        # Serializes local mutations with generation admission; no lock spans model network IO.
        self.lock = asyncio.Lock()
        self.generations = None

    @staticmethod
    def name_conversation(conversation: Conversation, text: str, filenames: list[str]):
        if conversation.title_source != "default":
            return
        if text.strip():
            title = plain_preview(text, 32)
        else:
            title = f"附件：{filenames[0]}" if filenames else ""
        if title:
            conversation.title = title[:200]
            conversation.title_source = "auto"

    async def initialize_titles(self):
        async with self.db.sessions.begin() as session:
            conversations = await session.scalars(
                select(Conversation).where(Conversation.title_source == "default")
            )
            for conversation in conversations:
                first = await session.scalar(
                    select(Message)
                    .where(Message.conversation_id == conversation.id, Message.role == "user")
                    .order_by(Message.seq)
                    .limit(1)
                )
                if first:
                    self.name_conversation(
                        conversation, first.content, [item.name for item in first.attachments]
                    )

    async def require_conversation(self, session: AsyncSession, conversation_id: str):
        item = await session.get(Conversation, conversation_id)
        if item is None:
            raise AppError(404, "CONVERSATION_NOT_FOUND", "会话不存在。")
        return item

    async def require_message(self, session: AsyncSession, message_id: str):
        item = await session.get(Message, message_id)
        if item is None:
            raise AppError(404, "MESSAGE_NOT_FOUND", "消息不存在。")
        return item

    async def conversation_data(self, session: AsyncSession, conversation: Conversation):
        count = await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation.id)
        )
        last = await session.scalar(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.seq.desc())
            .limit(1)
        )
        return {
            "id": conversation.id,
            "title": conversation.title,
            "current_role_id": conversation.current_role_id,
            "context_segment": conversation.context_segment,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "message_count": count,
            "preview": plain_preview(last.content) if last else "",
        }

    async def list_conversations(self, include_empty: bool = False, query: str = ""):
        async with self.db.sessions() as session:
            conversations = (
                await session.scalars(
                    select(Conversation).order_by(Conversation.updated_at.desc(), Conversation.id)
                )
            ).all()
            result = []
            for conversation in conversations:
                item = await self.conversation_data(session, conversation)
                if not include_empty and not item["message_count"]:
                    continue
                if query and query.casefold() not in (item["title"] + item["preview"]).casefold():
                    continue
                result.append(item)
            return {"items": result}

    async def create_conversation(self, role_id: str):
        validate_role(role_id)
        async with self.lock, self.db.sessions.begin() as session:
            conversation = await session.scalar(
                select(Conversation)
                .where(
                    ~select(Message.id).where(Message.conversation_id == Conversation.id).exists()
                )
                .order_by(Conversation.created_at.desc())
                .limit(1)
            )
            if conversation is None:
                conversation = Conversation(current_role_id=role_id)
                session.add(conversation)
                await session.flush()
            elif conversation.current_role_id != role_id:
                conversation.current_role_id = role_id
                conversation.context_segment = new_id()
            return await self.conversation_data(session, conversation)

    async def patch_conversation(
        self, conversation_id: str, title: str | None, role_id: str | None
    ):
        if role_id is not None:
            validate_role(role_id)
        if title is not None and not title.strip():
            raise AppError(422, "EMPTY_TITLE", "会话标题不能为空。")
        async with self.lock, self.db.sessions.begin() as session:
            conversation = await self.require_conversation(session, conversation_id)
            if role_id is not None and role_id != conversation.current_role_id:
                self.generations.check_context_mutable(conversation_id)
                conversation.current_role_id = role_id
                conversation.context_segment = new_id()
            if title is not None:
                conversation.title = title.strip()
                conversation.title_source = "manual"
            conversation.updated_at = now()
            await session.flush()
            return await self.conversation_data(session, conversation)

    async def get_messages(self, conversation_id: str, before_seq: int | None, limit: int):
        async with self.db.sessions() as session:
            await self.require_conversation(session, conversation_id)
            query = select(Message).where(Message.conversation_id == conversation_id)
            if before_seq is not None:
                query = query.where(Message.seq < before_seq)
            result = (
                await session.scalars(query.order_by(Message.seq.desc()).limit(limit + 1))
            ).all()
            return {
                "items": [message_data(item) for item in reversed(result[:limit])],
                "has_more": len(result) > limit,
            }

    async def get_message(self, message_id: str):
        async with self.db.sessions() as session:
            return message_data(await self.require_message(session, message_id))

    async def delete_message(self, message_id: str):
        async with self.lock:
            async with self.db.sessions() as session:
                message = await self.require_message(session, message_id)
                conversation_id = message.conversation_id
                if message.request_id:
                    self.generations.accepted_request_ids.add(message.request_id)
                active = self.generations.active
                if active and active.conversation_id == conversation_id:
                    if message.id != active.message_id:
                        raise AppError(409, "GENERATION_BUSY", "请先停止当前生成再删除消息。")
                    await self.generations.cancel_active()
            async with self.db.sessions.begin() as session:
                await session.execute(delete(Message).where(Message.id == message_id))
                conversation = await self.require_conversation(session, conversation_id)
                conversation.updated_at = now()

    async def delete_conversations(self, conversation_id: str | None = None):
        async with self.lock:
            if conversation_id:
                async with self.db.sessions() as session:
                    await self.require_conversation(session, conversation_id)
            active = self.generations.active
            if active and (conversation_id is None or active.conversation_id == conversation_id):
                await self.generations.cancel_active()
            async with self.db.sessions.begin() as session:
                requests = select(Message.request_id).where(Message.request_id.is_not(None))
                if conversation_id:
                    requests = requests.where(Message.conversation_id == conversation_id)
                self.generations.accepted_request_ids.update(await session.scalars(requests))
                query = delete(Conversation)
                if conversation_id:
                    query = query.where(Conversation.id == conversation_id)
                await session.execute(query)

    async def import_history(self, normalized: dict):
        counts = {"imported_conversations": 0, "imported_messages": 0, "skipped_conversations": 0}
        async with self.lock:
            if self.generations.active is not None:
                raise AppError(409, "GENERATION_BUSY", "请等待当前回复完成或停止生成后再导入记录。")
            async with self.db.sessions.begin() as session:
                for source in normalized["conversations"]:
                    existing = await session.scalar(
                        select(Conversation.id).where(
                            Conversation.import_identity == source["import_identity"]
                        )
                    )
                    if existing:
                        counts["skipped_conversations"] += 1
                        continue
                    conversation = Conversation(
                        title=source["title"],
                        title_source="default" if source["title"] == "新对话" else "manual",
                        current_role_id=source["current_role_id"],
                        context_segment=source["context_segment"],
                        import_identity=source["import_identity"],
                        next_seq=len(source["messages"]) + 1,
                    )
                    session.add(conversation)
                    await session.flush()
                    # Imported records lack original timestamps; do not invent them.
                    conversation.created_at = source.get("created_at")
                    conversation.updated_at = source.get("updated_at")
                    message_ids = [new_id() for _ in source["messages"]]
                    for index, original in enumerate(source["messages"]):
                        related_index = original.get("related_user_index")
                        message = Message(
                            id=message_ids[index],
                            conversation_id=conversation.id,
                            seq=index + 1,
                            role=original["role"],
                            content=original["content"],
                            role_id=original.get("role_id"),
                            context_segment=original.get("context_segment"),
                            mode=original.get("mode"),
                            status=original.get("status", "completed"),
                            related_user_message_id=(
                                message_ids[related_index] if related_index is not None else None
                            ),
                            attachments=[
                                Attachment(**item) for item in original.get("attachments", [])
                            ],
                        )
                        session.add(message)
                        await session.flush()
                        message.created_at = original.get("created_at")
                        if message.role == "user":
                            self.name_conversation(
                                conversation,
                                message.content,
                                [item.name for item in message.attachments],
                            )
                    counts["imported_conversations"] += 1
                    counts["imported_messages"] += len(source["messages"])
        return counts

    async def build_context(
        self,
        session: AsyncSession,
        conversation_id: str,
        role_id: str,
        segment: str,
        through_seq: int | None = None,
    ):
        query = select(Message).where(
            Message.conversation_id == conversation_id,
            Message.context_segment == segment,
            Message.status != "generating",
        )
        if through_seq is not None:
            query = query.where(Message.seq <= through_seq)
        messages = (await session.scalars(query.order_by(Message.seq))).all()
        result = [{"role": "system", "content": ROLES[role_id]["system_prompt"]}]
        for message in messages:
            content = message.content
            for attachment in message.attachments:
                content += (
                    f"\n\n附件：{attachment.name}（{attachment.size} 字节，{attachment.mime}）\n"
                    f"{attachment.extracted_text or attachment.note or '无可提取正文'}"
                )
            if content.strip():
                result.append({"role": message.role, "content": content})
        return result
