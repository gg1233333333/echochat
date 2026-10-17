"""Durable run lifecycle; message text remains the atomic display checkpoint."""

from sqlalchemy import select

from app.errors import AppError
from app.models import Run, RunEvent, now

TRANSITIONS = {
    "queued": {"running", "cancelled", "failed", "interrupted"},
    "running": {"completed", "cancelled", "failed", "interrupted"},
    "completed": set(),
    "cancelled": set(),
    "failed": set(),
    "interrupted": set(),
}


def append_event(session, run: Run, kind: str, payload: dict):
    run.last_event_seq += 1
    run.updated_at = now()
    session.add(RunEvent(run_id=run.id, seq=run.last_event_seq, kind=kind, payload=payload))


def transition(session, run: Run, state: str, **detail):
    if run.state == state:
        return
    if state not in TRANSITIONS.get(run.state, set()):
        raise AppError(409, "RUN_STATE", f"运行状态不能从 {run.state} 转为 {state}。")
    run.state = state
    append_event(session, run, f"run_{state}", detail)


def run_data(run: Run):
    return {
        "run_id": run.id,
        "request_id": run.request_id,
        "message_id": run.message_id,
        "conversation_id": run.conversation_id,
        "state": run.state,
        "task": run.task,
        "checkpoint": run.checkpoint,
        "last_event_seq": run.last_event_seq,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "resume_supported": False,
    }


class RunService:
    def __init__(self, database):
        self.db = database

    async def require(self, session, run_id):
        run = await session.get(Run, run_id)
        if run is None:
            raise AppError(404, "RUN_NOT_FOUND", "运行记录不存在或所属消息已删除。")
        return run

    async def read(self, run_id):
        async with self.db.sessions() as session:
            return run_data(await self.require(session, run_id))

    async def for_message(self, message_id):
        async with self.db.sessions() as session:
            run = await session.scalar(select(Run).where(Run.message_id == message_id))
            if run is None:
                raise AppError(404, "RUN_NOT_FOUND", "该消息没有运行记录。")
            return run_data(run)

    async def events(self, run_id, after_seq=0, limit=100):
        async with self.db.sessions() as session:
            run = await self.require(session, run_id)
            rows = await session.scalars(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
                .order_by(RunEvent.seq)
                .limit(limit)
            )
            items = [
                {
                    "run_id": row.run_id,
                    "seq": row.seq,
                    "kind": row.kind,
                    "payload": row.payload,
                    "created_at": row.created_at,
                }
                for row in rows
            ]
            cursor = items[-1]["seq"] if items else after_seq
            return {
                "items": items,
                "next_after_seq": cursor,
                "has_more": cursor < run.last_event_seq,
            }

    async def record(self, run_id, kind, payload, checkpoint=None):
        async with self.db.sessions.begin() as session:
            run = await self.require(session, run_id)
            if run.state != "running":
                raise AppError(409, "RUN_STATE", "运行结束后不能追加执行事件。")
            if checkpoint is not None:
                run.checkpoint = checkpoint
            append_event(session, run, kind, payload)
            return {"run_id": run.id, "seq": run.last_event_seq, "kind": kind, "payload": payload}
