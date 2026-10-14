import secrets
import uuid
from contextlib import asynccontextmanager

import anyio
import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .errors import ChatError
from .schemas import ChatRequest
from .sse import event
from .streaming import ManagedStreamingResponse, relay_events


class BodyLimitMiddleware:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        size = 0
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.max_bytes:
                error = ChatError("request_too_large", "请求体过大，请缩短上下文。", 413)
                response = JSONResponse({"error": error.payload(uuid.uuid4().hex)}, status_code=413)
                return await response(scope, receive, send)
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay_receive():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, send)


def create_app(settings: Settings | None = None, transport=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        timeout = httpx.Timeout(
            connect=settings.connect_timeout_seconds,
            read=settings.read_timeout_seconds,
            write=10,
            pool=5,
        )
        async with httpx.AsyncClient(
            timeout=timeout,
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=settings.max_concurrent_streams),
        ) as client:
            app.state.client = client
            app.state.active_streams = 0
            yield

    app = FastAPI(
        title="EchoChat API",
        lifespan=lifespan,
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None,
    )
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["POST", "GET"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Request-ID"],
        allow_credentials=False,
    )

    @app.exception_handler(ChatError)
    async def handle_chat_error(request, exc):
        return JSONResponse({"error": exc.payload(uuid.uuid4().hex)}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request, exc):
        # Pydantic's default errors echo input values. Return a safe, stable envelope.
        error = ChatError("invalid_request", "消息或模式无效，或上下文超过限制。", 422)
        return JSONResponse({"error": error.payload(uuid.uuid4().hex)}, status_code=422)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.post("/api/chat/stream")
    async def chat(payload: ChatRequest, request: Request):
        if settings.app_env == "production":
            supplied = request.headers.get("x-echochat-gateway-token", "")
            expected = settings.gateway_token.get_secret_value()
            if not secrets.compare_digest(supplied.encode(), expected.encode()):
                raise ChatError("unauthorized", "请先通过站点身份验证。", 401)
        elif not request.client or request.client.host not in ("127.0.0.1", "::1"):
            raise ChatError("local_only", "开发模式仅允许本机访问。", 403)
        if request.headers.get("origin") not in (None, *settings.cors_origins):
            raise ChatError("origin_not_allowed", "此来源不允许访问对话接口。", 403)
        request_id = uuid.uuid4().hex

        async def body():
            # Enter inside the iterator so a response cancelled before its first byte
            # cannot leak a concurrency slot. No await between check and increment.
            if app.state.active_streams >= settings.max_concurrent_streams:
                yield event(
                    "error",
                    ChatError("server_busy", "服务繁忙，请稍后重试。", 503, True).payload(
                        request_id
                    ),
                )
                return
            app.state.active_streams += 1
            source = relay_events(app.state.client, settings, payload, request_id)
            try:
                async for item in source:
                    yield item
            finally:
                with anyio.CancelScope(shield=True):
                    await source.aclose()
                    app.state.active_streams -= 1

        return ManagedStreamingResponse(
            body(),
            total_timeout=settings.stream_timeout_seconds + 5,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store",
                "X-Accel-Buffering": "no",
                "X-Request-ID": request_id,
            },
        )

    return app
