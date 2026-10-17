from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return str(uuid4())


def now() -> str:
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    title_source: Mapped[str] = mapped_column(
        String(16), default="default", server_default="default"
    )
    current_role_id: Mapped[str] = mapped_column(String(30), default="general")
    context_segment: Mapped[str] = mapped_column(String(36), default=new_id)
    created_at: Mapped[str | None] = mapped_column(String(40), default=now)
    updated_at: Mapped[str | None] = mapped_column(String(40), default=now)
    import_identity: Mapped[str | None] = mapped_column(String(128), unique=True)
    next_seq: Mapped[int] = mapped_column(default=1)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq"),
        Index("ix_messages_conversation_segment", "conversation_id", "context_segment"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int]
    role: Mapped[str] = mapped_column(String(12))
    content: Mapped[str] = mapped_column(Text, default="")
    reasoning_content: Mapped[str] = mapped_column(Text, default="", server_default="")
    agent_steps: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    role_id: Mapped[str | None] = mapped_column(String(30))
    context_segment: Mapped[str | None] = mapped_column(String(36))
    mode: Mapped[str | None] = mapped_column(String(30))
    related_user_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    request_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    regenerated_from_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20), default="completed")
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    finish_reason: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[str | None] = mapped_column(String(40), default=now)
    attachments: Mapped[list["Attachment"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, lazy="selectin"
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, lazy="selectin"
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    mime: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text, deferred=True)


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    size: Mapped[int]
    mime: Mapped[str] = mapped_column(String(150))
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text)
    truncated: Mapped[bool] = mapped_column(default=False)
