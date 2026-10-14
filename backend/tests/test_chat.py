import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.sse import SSEDecoder

PAYLOAD = {"mode": "thinking", "messages": [{"role": "user", "content": "你好"}]}
KEY = "test-server-secret-never-return-this"


def settings(**kwargs):
    return Settings(deepseek_api_key=KEY, _env_file=None, **kwargs)


class SpyStream(httpx.AsyncByteStream):
    def __init__(self, chunks=(), *, block=False, error=None):
        self.chunks = chunks
        self.block = block
        self.error = error
        self.closed = False
        self.started = asyncio.Event()

    async def __aiter__(self):
        self.started.set()
        for chunk in self.chunks:
            yield chunk
        if self.error:
            raise self.error
        if self.block:
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


def provider_chunk(content):
    return (
        "data: "
        + json.dumps({"choices": [{"delta": {"content": content}}]}, ensure_ascii=False)
        + "\n\n"
    ).encode()


async def call_api(handler, *, config=None, payload=PAYLOAD, headers=None, client_host="127.0.0.1"):
    app = create_app(config or settings(), transport=httpx.MockTransport(handler))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(client_host, 1234)),
            base_url="http://localhost",
        ) as client:
            response = await client.post("/api/chat/stream", json=payload, headers=headers)
        assert app.state.active_streams == 0
    assert app.state.client.is_closed
    return response


async def test_stream_preserves_utf8_and_whitelists_request():
    captured = []
    data = provider_chunk("你好😊") + b"data: [DONE]\r\n\r\n"
    source = SpyStream([data[i : i + 1] for i in range(len(data))])

    def handler(request):
        captured.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=source)

    result = await call_api(handler)
    assert result.status_code == 200
    assert "你好😊" in result.text
    assert result.text.count("event: done") == 1
    assert source.closed
    sent = json.loads(captured[0].content)
    assert sent["model"] == "deepseek-flash"
    assert sent["thinking"] == {"type": "enabled"}
    assert sent["reasoning_effort"] == "high"
    assert sent["max_tokens"] == 4096
    assert captured[0].headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in result.text
    assert result.headers["x-accel-buffering"] == "no"


async def test_non_thinking_and_reasoning_only_frames():
    source = SpyStream(
        [
            b'data: {"choices":[{"delta":{"reasoning_content":"private thinking"}}]}\n\n',
            provider_chunk("answer"),
            b"data: [DONE]\n\n",
        ]
    )

    def handler(request):
        payload = json.loads(request.content)
        assert payload["thinking"] == {"type": "disabled"}
        assert "reasoning_effort" not in payload
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=source)

    result = await call_api(handler, payload={**PAYLOAD, "mode": "non-thinking"})
    assert "private thinking" not in result.text
    assert "answer" in result.text
    assert source.closed


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "upstream_invalid_request"),
        (401, "upstream_authentication"),
        (403, "upstream_authentication"),
        (402, "upstream_quota_exceeded"),
        (429, "upstream_rate_limited"),
        (500, "upstream_unavailable"),
        (302, "upstream_invalid_request"),
    ],
)
async def test_upstream_http_errors_are_sanitized(status, code):
    response = await call_api(lambda request: httpx.Response(status, text=KEY))
    assert f'"code": "{code}"' in response.text
    assert "event: done" not in response.text
    assert KEY not in response.text


@pytest.mark.parametrize(
    "chunks,code",
    [
        ([b"data: not-json\n\n"], "upstream_protocol"),
        ([b'data: {"choices":42}\n\n'], "upstream_protocol"),
        ([provider_chunk("partial")], "upstream_truncated"),
        ([b"data: \xff\n\n"], "upstream_protocol"),
        ([b"data: " + b"x" * 65537], "upstream_protocol"),
    ],
)
async def test_bad_or_incomplete_streams_close_upstream(chunks, code):
    source = SpyStream(chunks)
    response = await call_api(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=source
        )
    )
    assert f'"code": "{code}"' in response.text
    assert source.closed


@pytest.mark.parametrize(
    "error,code",
    [
        (httpx.ConnectTimeout("secret"), "upstream_timeout"),
        (httpx.ReadTimeout("secret"), "upstream_timeout"),
        (httpx.ConnectError("secret"), "upstream_network"),
    ],
)
async def test_transport_failure_classification(error, code):
    async def handler(request):
        raise error

    response = await call_api(handler)
    assert f'"code": "{code}"' in response.text
    assert "secret" not in response.text


async def test_total_deadline_heartbeats_and_cleanup():
    source = SpyStream(block=True)
    response = await call_api(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=source
        ),
        config=settings(stream_timeout_seconds=0.05, heartbeat_seconds=0.01),
    )
    assert ": keepalive" in response.text
    assert '"code": "stream_timeout"' in response.text
    assert source.closed


@pytest.mark.parametrize(
    "payload",
    [
        {**PAYLOAD, "mode": "unknown"},
        {**PAYLOAD, "model": "arbitrary"},
        {**PAYLOAD, "messages": []},
        {**PAYLOAD, "messages": [{"role": "user", "content": "a" * 32001}]},
        {**PAYLOAD, "messages": [{"role": "assistant", "content": "no user"}]},
        {**PAYLOAD, "messages": [{"role": "user", "content": "x", "api_key": KEY}]},
    ],
)
async def test_validation_rejects_unbounded_and_unknown_inputs(payload):
    def handler(request):
        pytest.fail("Invalid request must not call the provider")

    response = await call_api(handler, payload=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert KEY not in response.text


async def test_body_limit_before_json_parsing():
    response = await call_api(
        lambda request: pytest.fail("must not call provider"),
        config=settings(max_request_bytes=1024),
        payload={**PAYLOAD, "messages": [{"role": "user", "content": "x" * 2048}]},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


async def test_production_gateway_auth_and_origin_are_required():
    token = "g" * 32
    config = settings(app_env="production", gateway_token=token)

    def deny(request):
        pytest.fail("must not call provider")

    response = await call_api(deny, config=config)
    assert response.status_code == 401
    response = await call_api(
        deny,
        config=config,
        headers={"X-EchoChat-Gateway-Token": token, "Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    response = await call_api(
        lambda request: httpx.Response(429),
        config=config,
        headers={"X-EchoChat-Gateway-Token": token},
    )
    assert "upstream_rate_limited" in response.text


async def test_development_is_loopback_only():
    response = await call_api(
        lambda request: pytest.fail("must not call provider"), client_host="203.0.113.4"
    )
    assert response.status_code == 403


def test_fail_fast_configuration():
    with pytest.raises(ValidationError):
        settings(app_env="production")
    with pytest.raises(ValidationError):
        Settings(deepseek_api_key="", _env_file=None)
    with pytest.raises(ValidationError):
        settings(cors_origins=["*"])


def test_sse_crlf_comments_multiline():
    parser = SSEDecoder()
    events = []
    for char in ': ping\r\ndata: {\r\ndata: "x": 1}\r\n\r\n':
        events.extend(parser.feed(char))
    assert events == ['{\n"x": 1}']
    with pytest.raises(Exception, match="upstream_protocol"):
        SSEDecoder(max_size=10).feed("data:\ndata:\ndata:\n")


async def asgi_request(app, disconnected, *, send_hook=None):
    body_sent = False
    collected = []

    async def receive():
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": json.dumps(PAYLOAD).encode()}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        collected.append(message)
        if send_hook:
            await send_hook(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/chat/stream",
        "raw_path": b"/api/chat/stream",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"localhost"), (b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1234),
        "server": ("localhost", 8000),
    }
    await app(scope, receive, send)
    return collected


async def test_disconnect_during_idle_read_releases_stream_and_slot():
    source = SpyStream([provider_chunk("partial")], block=True)
    app = create_app(
        settings(),
        httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=source
            )
        ),
    )
    disconnected = asyncio.Event()
    async with app.router.lifespan_context(app):
        task = asyncio.create_task(asgi_request(app, disconnected))
        await asyncio.wait_for(source.started.wait(), 1)
        disconnected.set()
        await asyncio.wait_for(task, 1)
        assert source.closed
        assert app.state.active_streams == 0


async def test_disconnect_before_upstream_headers_cancels_connection():
    opened, cancelled, disconnected = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def handler(request):
        opened.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    app = create_app(settings(), httpx.MockTransport(handler))
    async with app.router.lifespan_context(app):
        task = asyncio.create_task(asgi_request(app, disconnected))
        await asyncio.wait_for(opened.wait(), 1)
        disconnected.set()
        await asyncio.wait_for(task, 1)
        assert cancelled.is_set()
        assert app.state.active_streams == 0


async def test_busy_request_is_rejected_without_opening_another_upstream():
    source = SpyStream(block=True)
    app = create_app(
        settings(max_concurrent_streams=1),
        httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=source
            )
        ),
    )
    disconnected = asyncio.Event()
    async with app.router.lifespan_context(app):
        first = asyncio.create_task(asgi_request(app, disconnected))
        await asyncio.wait_for(source.started.wait(), 1)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            second = await client.post("/api/chat/stream", json=PAYLOAD)
        assert "server_busy" in second.text
        assert app.state.active_streams == 1
        disconnected.set()
        await asyncio.wait_for(first, 1)
        assert source.closed
        assert app.state.active_streams == 0


async def test_failed_downstream_send_closes_suspended_generator():
    source = SpyStream([provider_chunk("partial")], block=True)
    app = create_app(
        settings(),
        httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=source
            )
        ),
    )

    async def fail_send(message):
        if message["type"] == "http.response.body":
            raise OSError("client socket gone")

    async with app.router.lifespan_context(app):
        with pytest.raises(ExceptionGroup):
            await asgi_request(app, asyncio.Event(), send_hook=fail_send)
        assert source.closed
        assert app.state.active_streams == 0
