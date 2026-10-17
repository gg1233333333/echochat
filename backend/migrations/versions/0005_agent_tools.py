"""Store agent protocol steps and downloadable text artifacts."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "messages", sa.Column("agent_steps", sa.JSON(), nullable=False, server_default="[]")
    )
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("message_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("mime", sa.String(100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_artifacts_message_id", "artifacts", ["message_id"])


def downgrade():
    op.drop_table("artifacts")
    op.drop_column("messages", "agent_steps")
