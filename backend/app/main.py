import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, urlsplit

import httpx
from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.attachments import (
    ATTACHMENT_LIMITS,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_TOTAL_BYTES,
    AttachmentError,
    parse_attachments,
)
from app.database import Database
from app.errors import AppError
from app.generation import GenerationService
from app.legacy import LegacyError, normalize_legacy_snapshot
from app.models import AppSetting, Artifact
from app.options import MODES, ROLES
from app.providers import ChatCompletionsProvider, ProviderSettings
from app.service import ChatService
from app.tools import TOOL_DEFINITIONS

MAX_REQUEST_BYTES = 32 * 1024 * 1024


class GenerationResponse(StreamingResponse):
    def __init__(self, service: GenerationService, generation):
        self.service = service
        self.generation = generation
        super().__init__(
            service.stream(generation),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # A failed response send may leave the iterator suspended at its last yield.
            self.service.disconnect(self.generation)


class LocalRequestMiddleware:
    def __init__(self, app, allowed_origins: set[str]):
        self.app = app
        self.allowed_origins = allowed_origins

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {key.lower(): value for key, value in scope["headers"]}
        host = headers.get(b"host", b"").decode("latin-1")
        origin = headers.get(b"origin", b"").decode("latin-1")
        try:
            hostname = urlsplit(f"//{host}").hostname
        except ValueError:
            hostname = None
        if hostname not in {"localhost", "127.0.0.1", "::1"}:
            return await self.reject(scope, receive, send, 403, "INVALID_HOST", "仅允许本机访问。")
        if origin and origin not in self.allowed_origins:
            return await self.reject(
                scope, receive, send, 403, "INVALID_ORIGIN", "请求来源不受信任。"
            )
        # Buffer only the bounded request body before multipart can spool files to disk.
        if scope["method"] in {"POST", "PUT", "PATCH"}:
            chunks, size = [], 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                part = message.get("body", b"")
                size += len(part)
                if size > MAX_REQUEST_BYTES:
                    return await self.reject(
                        scope, receive, send, 413, "REQUEST_TOO_LARGE", "请求内容超过 32 MiB 限制。"
                    )
                chunks.append(part)
                if not message.get("more_body", False):
                    break
            body = b"".join(chunks)
            delivered = False

            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            return await self.app(scope, bounded_receive, send)
        return await self.app(scope, receive, send)

    @staticmethod
    async def reject(scope, receive, send, status: int, code: str, message: str):
        response = JSONResponse({"detail": {"code": code, "message": message}}, status_code=status)
        await response(scope, receive, send)


class CreateConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_id: str = "general"


class UpdateConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=200)
    role_id: str | None = None


class Regenerate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    mode: str
    agent_enabled: bool = False
    allowed_tools: list[str] | None = None


class ConfigureProvider(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    base_url: str
    model: str
    protocol: str


class ImportHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: dict


def create_app(
    database_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    data_dir: Path | str | None = None,
    allowed_origins: set[str] | None = None,
) -> FastAPI:
    directory = Path(data_dir) if data_dir else Path(__file__).resolve().parents[1] / "data"
    db_url = database_url or f"sqlite+aiosqlite:///{directory / 'echochat.db'}"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        directory.mkdir(parents=True, exist_ok=True)
        database = Database(db_url)
        await database.initialize()
        async with httpx.AsyncClient(
            transport=transport, timeout=httpx.Timeout(120, connect=15), trust_env=False
        ) as client:
            chats = ChatService(database)
            await chats.initialize_titles()
            generations = GenerationService(chats, client)
            async with database.sessions() as session:
                saved = await session.get(AppSetting, "provider")
                if saved:
                    generations.provider_settings = ProviderSettings(**saved.value)
            chats.generations = generations
            app.state.chats = chats
            app.state.generations = generations
            try:
                yield
            finally:
                await generations.cancel_active()
                generations.api_key = None
        await database.close()

    application = FastAPI(title="EchoChat", version="0.1.0", lifespan=lifespan)
    origins = allowed_origins or {
        f"http://{host}:{port}"
        for host in ("localhost", "127.0.0.1")
        for port in (5173, 5178, 8000)
    }
    application.add_middleware(LocalRequestMiddleware, allowed_origins=origins)

    @application.exception_handler(AppError)
    async def app_error_handler(_, error: AppError):
        return JSONResponse(
            {"detail": {"code": error.code, "message": error.message}},
            status_code=error.status_code,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_handler(_, error):
        # Do not reflect submitted secrets or chat content in validation responses.
        detail = [
            {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
            for item in error.errors()
        ]
        return JSONResponse({"detail": detail}, status_code=422)

    @application.get("/api/options")
    async def options():
        return {
            "roles": [
                {k: v for k, v in role.items() if k != "system_prompt"} for role in ROLES.values()
            ],
            "modes": [{"value": key, "label": value["label"]} for key, value in MODES.items()],
            "attachments": ATTACHMENT_LIMITS,
            "tools": [
                {"name": name, "label": value[1], "description": value[2]}
                for name, value in TOOL_DEFINITIONS.items()
            ],
        }

    @application.get("/api/provider")
    async def get_provider(request: Request):
        return request.app.state.generations.provider_settings.data()

    @application.put("/api/provider")
    async def configure_provider(request: Request, data: ConfigureProvider):
        settings = ProviderSettings(**data.model_dump())
        generations = request.app.state.generations
        async with generations.chats.lock:
            if generations.active:
                raise AppError(409, "GENERATION_BUSY", "请先停止当前运行再修改模型服务。")
            previous = generations.provider_settings
            async with generations.chats.db.sessions.begin() as session:
                await session.merge(AppSetting(key="provider", value=settings.data()))
            generations.provider_settings = settings
            if (previous.base_url, previous.protocol) != (settings.base_url, settings.protocol):
                generations.api_key = None
        return {**settings.data(), "configured": bool(generations.api_key)}

    @application.post("/api/provider/test")
    async def test_provider(request: Request):
        generations = request.app.state.generations
        return await ChatCompletionsProvider(
            generations.client, generations.provider_settings
        ).test_connection(generations.api_key)

    @application.get("/api/runs/{run_id}")
    async def get_run(request: Request, run_id: str):
        return await request.app.state.generations.runs.read(run_id)

    @application.post("/api/runs/{run_id}/cancel")
    async def cancel_run(request: Request, run_id: str):
        generations = request.app.state.generations
        run = await generations.runs.read(run_id)
        await generations.cancel(run["request_id"])
        return await generations.runs.read(run_id)

    @application.get("/api/runs/{run_id}/events")
    async def run_events(
        request: Request,
        run_id: str,
        after_seq: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ):
        return await request.app.state.generations.runs.events(run_id, after_seq, limit)

    @application.get("/api/credentials/deepseek")
    async def get_credential(request: Request):
        return {"configured": bool(request.app.state.generations.api_key)}

    @application.put("/api/credentials/deepseek")
    async def put_credential(request: Request):
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise AppError(422, "INVALID_KEY", "请提供有效的 API Key。") from None
        key = data.get("api_key") if isinstance(data, dict) else None
        if (
            not isinstance(key, str)
            or not key.strip()
            or len(key) > 1024
            or any(ord(char) < 33 or ord(char) > 126 for char in key.strip())
        ):
            raise AppError(422, "INVALID_KEY", "请提供有效的 API Key。")
        generations = request.app.state.generations
        async with generations.chats.lock:
            settings = generations.provider_settings
            target = data.get("target")
            expected = {"base_url": settings.base_url, "protocol": settings.protocol}
            default = ProviderSettings()
            legacy = target is None and expected == {
                "base_url": default.base_url, "protocol": default.protocol
            }
            if not legacy and target != expected:
                raise AppError(
                    409, "CREDENTIAL_TARGET_CHANGED",
                    "模型服务已更改，请重新打开密钥设置并核对目标地址。",
                )
            generations.api_key = key.strip()
        return {"configured": True}

    @application.delete("/api/credentials/deepseek")
    async def clear_credential(request: Request):
        generations = request.app.state.generations
        async with request.app.state.chats.lock:
            await generations.cancel_active()
            generations.api_key = None
        return {"configured": False}

    @application.get("/api/conversations")
    async def conversations(request: Request, include_empty: bool = False, q: str = ""):
        return await request.app.state.chats.list_conversations(include_empty, q)

    @application.post("/api/conversations")
    async def create_conversation(request: Request, data: CreateConversation):
        return await request.app.state.chats.create_conversation(data.role_id)

    @application.patch("/api/conversations/{conversation_id}")
    async def update_conversation(request: Request, conversation_id: str, data: UpdateConversation):
        return await request.app.state.chats.patch_conversation(
            conversation_id, data.title, data.role_id
        )

    @application.delete("/api/conversations", status_code=204)
    async def clear_conversations(request: Request):
        await request.app.state.chats.delete_conversations()
        return Response(status_code=204)

    @application.delete("/api/conversations/{conversation_id}", status_code=204)
    async def delete_conversation(request: Request, conversation_id: str):
        await request.app.state.chats.delete_conversations(conversation_id)
        return Response(status_code=204)

    @application.get("/api/conversations/{conversation_id}/messages")
    async def get_messages(
        request: Request,
        conversation_id: str,
        before_seq: int | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ):
        return await request.app.state.chats.get_messages(conversation_id, before_seq, limit)

    @application.get("/api/messages/{message_id}")
    async def get_message(request: Request, message_id: str):
        return await request.app.state.chats.get_message(message_id)

    @application.get("/api/artifacts/{artifact_id}/download")
    async def download_artifact(request: Request, artifact_id: str):
        async with request.app.state.chats.db.sessions() as session:
            row = (
                await session.execute(
                    select(Artifact.name, Artifact.content).where(Artifact.id == artifact_id)
                )
            ).first()
            if row is None:
                raise AppError(404, "ARTIFACT_NOT_FOUND", "文件不存在或所属对话已删除。")
            return Response(
                row.content.encode("utf-8"),
                media_type="application/octet-stream",
                headers={
                    "Content-Disposition": "attachment; filename*=UTF-8''"
                    + quote(row.name, safe=""),
                    "X-Content-Type-Options": "nosniff",
                    "Cache-Control": "no-store",
                },
            )

    @application.delete("/api/messages/{message_id}", status_code=204)
    async def delete_message(request: Request, message_id: str):
        await request.app.state.chats.delete_message(message_id)
        return Response(status_code=204)

    def response_for(generations: GenerationService, generation):
        return GenerationResponse(generations, generation)

    @application.post("/api/conversations/{conversation_id}/messages")
    async def send_message(
        request: Request,
        conversation_id: str,
        text: Annotated[str, Form()] = "",
        mode: Annotated[str, Form()] = "thinking",
        request_id: Annotated[str, Form()] = "",
        files: Annotated[list[UploadFile] | None, File()] = None,
        agent_enabled: Annotated[bool, Form()] = False,
        allowed_tools: Annotated[str | None, Form()] = None,
    ):
        try:
            scope = json.loads(allowed_tools) if allowed_tools is not None else None
        except ValueError:
            raise AppError(422, "TOOL_SCOPE", "工具授权列表格式无效。") from None
        uploads, total = [], 0
        try:
            if len(files or []) > MAX_FILES:
                raise AppError(422, "TOO_MANY_FILES", f"最多上传 {MAX_FILES} 个附件。")
            for upload in files or []:
                content = await upload.read(MAX_FILE_BYTES + 1)
                total += len(content)
                if len(content) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                    raise AppError(
                        413, "ATTACHMENT_TOO_LARGE", "附件超过单个 8 MiB 或总计 24 MiB 限制。"
                    )
                uploads.append((upload.filename or "", upload.content_type, content))
            attachments = await asyncio.to_thread(parse_attachments, uploads)
        except AttachmentError as error:
            raise AppError(422, error.code, str(error)) from None
        finally:
            for upload in files or []:
                await upload.close()
        generations = request.app.state.generations
        generation = await generations.prepare(
            request_id=request_id,
            mode=mode,
            conversation_id=conversation_id,
            text=text,
            attachments=attachments,
            agent_enabled=agent_enabled,
            allowed_tools=scope,
        )
        return response_for(generations, generation)

    @application.post("/api/messages/{message_id}/regenerate")
    async def regenerate(request: Request, message_id: str, data: Regenerate):
        generations = request.app.state.generations
        generation = await generations.prepare(
            request_id=data.request_id,
            mode=data.mode,
            regenerate_id=message_id,
            agent_enabled=data.agent_enabled,
            allowed_tools=data.allowed_tools,
        )
        return response_for(generations, generation)

    @application.post("/api/generations/{request_id}/cancel")
    async def cancel(request: Request, request_id: str):
        return await request.app.state.generations.cancel(request_id)

    @application.post("/api/import/local-history")
    async def import_history(request: Request, data: ImportHistory):
        try:
            normalized = await asyncio.to_thread(normalize_legacy_snapshot, data.snapshot)
        except LegacyError as error:
            raise AppError(422, error.code, str(error)) from None
        return await request.app.state.chats.import_history(normalized)

    return application


app = create_app()
