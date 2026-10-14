import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Message


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
            await session.execute(
                update(Message)
                .where(Message.status == "generating")
                .values(
                    status="interrupted",
                    error_code="SERVER_RESTARTED",
                    error_message="服务已重启，上次生成已中断。",
                )
            )

    async def close(self):
        await self.engine.dispose()
