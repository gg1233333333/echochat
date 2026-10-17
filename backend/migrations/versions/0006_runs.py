"""Separate run lifecycle and ordered events from message presentation."""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), unique=True),
        sa.Column("message_id", sa.String(36), unique=True),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("task", sa.JSON(), nullable=False),
        sa.Column("checkpoint", sa.JSON(), nullable=False),
        sa.Column("last_event_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_runs_conversation_id", "runs", ["conversation_id"])
    op.create_table(
        "run_events",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("seq", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
    )
    op.add_column("artifacts", sa.Column("operation_id", sa.String(64)))
    op.create_index("ix_artifacts_operation_id", "artifacts", ["operation_id"], unique=True)
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
    )
    connection = op.get_bind()
    runs = sa.table(
        "runs",
        *[
            sa.column(name, type_)
            for name, type_ in (
                ("id", sa.String),
                ("request_id", sa.String),
                ("message_id", sa.String),
                ("conversation_id", sa.String),
                ("state", sa.String),
                ("task", sa.JSON),
                ("checkpoint", sa.JSON),
                ("last_event_seq", sa.Integer),
                ("error_code", sa.String),
                ("error_message", sa.Text),
                ("created_at", sa.String),
                ("updated_at", sa.String),
            )
        ],
    )
    events = sa.table(
        "run_events",
        sa.column("run_id", sa.String),
        sa.column("seq", sa.Integer),
        sa.column("kind", sa.String),
        sa.column("payload", sa.JSON),
        sa.column("created_at", sa.String),
    )
    imported_at = datetime.now(UTC).isoformat()
    rows = (
        connection.execute(
            sa.text(
                "SELECT id,request_id,conversation_id,status,role_id,error_code,"
                "error_message,created_at "
                "FROM messages WHERE role='assistant' AND request_id IS NOT NULL"
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        run_id = str(uuid4())
        state = "running" if row["status"] == "generating" else row["status"]
        connection.execute(
            runs.insert().values(
                id=run_id,
                request_id=row["request_id"],
                message_id=row["id"],
                conversation_id=row["conversation_id"],
                state=state,
                task={"role": row["role_id"], "output": "assistant_message", "legacy": True},
                checkpoint={
                    "version": 1,
                    "message_id": row["id"],
                    "resume_supported": False,
                    "model_calls": None,
                    "tool_calls": None,
                },
                last_event_seq=1,
                error_code=row["error_code"],
                error_message=row["error_message"],
                created_at=row["created_at"] or imported_at,
                updated_at=imported_at,
            )
        )
        connection.execute(
            events.insert().values(
                run_id=run_id,
                seq=1,
                kind="legacy_imported",
                payload={"state": state},
                created_at=imported_at,
            )
        )


def downgrade():
    op.drop_table("app_settings")
    op.drop_index("ix_artifacts_operation_id", table_name="artifacts")
    op.drop_column("artifacts", "operation_id")
    op.drop_table("run_events")
    op.drop_table("runs")
