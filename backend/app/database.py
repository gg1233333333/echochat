import asyncio
import copy
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Message, Run
from app.runs import transition


class Database:
    def __init__(self, url: str):
        self.url = url
        self.engine = create_async_engine(url)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

        @event.listens_for(self.engine.sync_engine, "connect")
        def set_pragmas(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            # Cascade-delete journals must not depend on the OS temporary directory.
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    async def initialize(self):
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
        config.set_main_option("sqlalchemy.url", self.url.replace("%", "%%"))
        await asyncio.to_thread(command.upgrade, config, "head")
        async with self.sessions.begin() as session:
            for message in await session.scalars(
                select(Message).where(Message.status == "generating")
            ):
                message.status = "interrupted"
                message.error_code = "SERVER_RESTARTED"
                message.error_message = "服务已重启，上次生成已中断。"
                steps = copy.deepcopy(message.agent_steps)
                for step in steps:
                    for tool in step["tools"]:
                        if tool["status"] in {"pending", "running"}:
                            tool.update(status="interrupted", result={"error": "服务已重启。"})
                message.agent_steps = steps
            for run in await session.scalars(
                select(Run).where(Run.state.in_(["queued", "running"]))
            ):
                run.error_code = "SERVER_RESTARTED"
                run.error_message = "服务已重启，上次运行已中断；不会自动续跑。"
                transition(session, run, "interrupted", error_code=run.error_code)

    async def close(self):
        await self.engine.dispose()
