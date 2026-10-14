"""Store the model's reasoning separately from its answer."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "messages", sa.Column("reasoning_content", sa.Text(), nullable=False, server_default="")
    )


def downgrade():
    op.drop_column("messages", "reasoning_content")
