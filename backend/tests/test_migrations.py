import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.database import Database
from app.main import create_app


async def test_migrations_match_models_and_upgrade_keeps_records(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'migrations.db'}"
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    await asyncio.to_thread(command.upgrade, config, "0001")
    database = Database(url)
    async with database.engine.begin() as connection:
        await connection.exec_driver_sql(
            "INSERT INTO conversations(id,title,current_role_id,context_segment,next_seq) "
            "VALUES('preserved','title','developer','segment',1)"
        )
        await connection.exec_driver_sql(
            "INSERT INTO messages(id,conversation_id,seq,role,content,status,role_id,"
            "context_segment) "
            "VALUES('old-answer','preserved',1,'assistant','saved answer','completed',"
            "'developer','segment')"
        )
    await database.initialize()
    await asyncio.to_thread(command.check, config)
    async with database.engine.connect() as connection:
        assert (
            await connection.exec_driver_sql("SELECT title FROM conversations")
        ).scalar() == "title"
        row = (
            await connection.exec_driver_sql("SELECT content,reasoning_content FROM messages")
        ).one()
        assert tuple(row) == ("saved answer", "")
        conversation = (
            await connection.exec_driver_sql(
                "SELECT title_source,current_role_id,context_segment FROM conversations"
            )
        ).one()
        assert tuple(conversation) == ("manual", "general", "segment")
        message = (
            await connection.exec_driver_sql("SELECT role_id,context_segment FROM messages")
        ).one()
        assert tuple(message) == ("general", "segment")
    await database.close()


async def test_old_default_title_is_named_and_reasoning_survives_the_merge(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'echochat.db'}"
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    await asyncio.to_thread(command.upgrade, config, "0003")
    database = Database(url)
    async with database.engine.begin() as connection:
        await connection.exec_driver_sql(
            "INSERT INTO conversations(id,title,current_role_id,context_segment,next_seq) "
            "VALUES('old-chat','新对话','developer','old-segment',3)"
        )
        await connection.exec_driver_sql(
            "INSERT INTO messages(id,conversation_id,seq,role,content,status,role_id,"
            "context_segment,reasoning_content) VALUES"
            "('question','old-chat',1,'user','如何 **连接数据库**？','completed',"
            "'developer','old-segment',''),"
            "('answer','old-chat',2,'assistant','saved answer','completed',"
            "'developer','old-segment','saved reasoning')"
        )
    await database.close()

    app = create_app(data_dir=tmp_path)
    async with app.router.lifespan_context(app):
        chats = app.state.chats
        history = await chats.get_messages("old-chat", None, 100)
        assert history["items"][-1]["reasoning_content"] == "saved reasoning"
        assert history["items"][-1]["content"] == "saved answer"
        assert all(item["context_segment"] == "old-segment" for item in history["items"])
        assert all(item["role_id"] == "general" for item in history["items"])
        conversation = (await chats.list_conversations())["items"][0]
        assert conversation["title"] == "如何 连接数据库？"
        await chats.patch_conversation("old-chat", "新对话", None)

    restarted = create_app(data_dir=tmp_path)
    async with restarted.router.lifespan_context(restarted):
        conversation = (await restarted.state.chats.list_conversations())["items"][0]
        assert conversation["title"] == "新对话"
