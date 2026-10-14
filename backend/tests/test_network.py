"""Real loopback TCP tests: HTTPX -> Uvicorn -> HTTPX -> a local SSE provider."""

import asyncio
import json
import socket
from contextlib import asynccontextmanager, nullcontext

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request

from app import streaming
from app.main import create_app
from app.streaming import ManagedStreamingResponse
from tests.test_chat import PAYLOAD, provider_chunk, settings


@asynccontextmanager
async def serve(app):
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(
        app, log_level="error", access_log=False, lifespan="on", timeout_graceful_shutdown=1
    )
    server = uvicorn.Server(config)
    server.capture_signals = nullcontext
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(3):
            while not server.started:
                if task.done():
                    await task
                await asyncio.sleep(0.005)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 3)
        sock.close()


@pytest.mark.parametrize("scenario", ["complete", "disconnect", "read_timeout"])
async def test_real_http_stream_lifecycle(monkeypatch, scenario):
    upstream_closed = asyncio.Event()
    upstream = FastAPI()

    @upstream.post("/v1/chat/completions")
    async def completions(request: Request):
        assert request.headers["authorization"].startswith("Bearer test-server")
        request_payload = await request.json()
        assert request_payload["messages"] == PAYLOAD["messages"]

        async def body():
            try:
                yield provider_chunk("真实HTTP中文😊")
                if scenario == "complete":
                    yield b"data: [DONE]\n\n"
                else:
                    await asyncio.Event().wait()
            finally:
                upstream_closed.set()

        return ManagedStreamingResponse(body(), total_timeout=5, media_type="text/event-stream")

    async with serve(upstream) as provider_url:
        monkeypatch.setattr(streaming, "DEEPSEEK_URL", provider_url + "/v1/chat/completions")
        backend = create_app(settings(read_timeout_seconds=0.08, heartbeat_seconds=0.01))
        async with serve(backend) as url:
            async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
                async with client.stream(
                    "POST", url + "/api/chat/stream", json=PAYLOAD
                ) as response:
                    assert response.status_code == 200
                    lines = []
                    async for line in response.aiter_lines():
                        lines.append(line)
                        if scenario == "disconnect" and line.startswith("data:"):
                            assert json.loads(line[5:])["content"] == "真实HTTP中文😊"
                            break
                text = "\n".join(lines)
                if scenario == "complete":
                    assert "真实HTTP中文😊" in text
                    assert "event: done" in text
                elif scenario == "read_timeout":
                    assert ": keepalive" in text
                    assert "upstream_timeout" in text
                    assert "event: done" not in text
            await asyncio.wait_for(upstream_closed.wait(), 1)
            async with asyncio.timeout(1):
                while backend.state.active_streams:
                    await asyncio.sleep(0.005)
            assert backend.state.active_streams == 0
        assert backend.state.client.is_closed
