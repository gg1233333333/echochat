"""Retain the regeneration target after replacing its message."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("regenerated_from_id", sa.String(36)))


def downgrade():
    op.drop_column("messages", "regenerated_from_id")
