"""Unify the assistant and track automatic versus manual conversation titles."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "conversations",
        sa.Column("title_source", sa.String(16), nullable=False, server_default="default"),
    )
    op.execute("UPDATE conversations SET title_source='manual' WHERE title<>'新对话'")
    op.execute(
        "UPDATE conversations SET current_role_id='general' WHERE current_role_id='developer'"
    )
    op.execute("UPDATE messages SET role_id='general' WHERE role_id='developer'")


def downgrade():
    op.drop_column("conversations", "title_source")
