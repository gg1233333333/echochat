"""Initial local chat storage."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("current_role_id", sa.String(30), nullable=False),
        sa.Column("context_segment", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40)),
        sa.Column("updated_at", sa.String(40)),
        sa.Column("import_identity", sa.String(128), unique=True),
        sa.Column("next_seq", sa.Integer(), nullable=False),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("role_id", sa.String(30)),
        sa.Column("context_segment", sa.String(36)),
        sa.Column("mode", sa.String(30)),
        sa.Column(
            "related_user_message_id",
            sa.String(36),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
        ),
        sa.Column("request_id", sa.String(36), unique=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text()),
        sa.Column("finish_reason", sa.String(80)),
        sa.Column("created_at", sa.String(40)),
        sa.UniqueConstraint("conversation_id", "seq"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index(
        "ix_messages_conversation_segment", "messages", ["conversation_id", "context_segment"]
    )
    op.create_table(
        "attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "message_id",
            sa.String(36),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("mime", sa.String(150), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("truncated", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_attachments_message_id", "attachments", ["message_id"])


def downgrade():
    op.drop_table("attachments")
    op.drop_table("messages")
    op.drop_table("conversations")
