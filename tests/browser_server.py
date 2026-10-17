"""Local browser-test backend. Uses an isolated database and a fake model."""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import httpx
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

RESULTS = Path(__file__).resolve().parents[1] / "test-results"
RESULTS.mkdir(exist_ok=True)
if sys.platform == "win32":
    # Use an existing absolute directory for SQLite cascade journals on Windows.
    sqlite_temp = RESULTS / "sqlite-temp"
    sqlite_temp.mkdir(exist_ok=True)
    os.environ["TEMP"] = os.environ["TMP"] = str(sqlite_temp)

from app.main import create_app  # noqa: E402


class ModelStream(httpx.AsyncByteStream):
    def __init__(
        self,
        pieces: list[str],
        delay: float,
        reasoning: list[str] | None = None,
        finish_delay: float = 0,
        fail_after_content: bool = False,
    ):
        self.pieces = pieces
        self.delay = delay
        self.reasoning = reasoning or []
        self.finish_delay = finish_delay
        self.fail_after_content = fail_after_content

    async def __aiter__(self):
        for content in self.reasoning:
            await asyncio.sleep(self.delay)
            event = {"choices": [{"delta": {"reasoning_content": content}, "finish_reason": None}]}
            yield f"data: {json.dumps(event)}\n\n".encode()
        for content in self.pieces:
            await asyncio.sleep(self.delay)
            event = {"choices": [{"delta": {"content": content}, "finish_reason": None}]}
            yield f"data: {json.dumps(event)}\n\n".encode()
        if self.finish_delay:
            await asyncio.sleep(self.finish_delay)
        if self.fail_after_content:
            event = {"error": {"message": "Test stream failed after partial output"}}
            yield f"data: {json.dumps(event)}\n\n".encode()
            return
        event = {"choices": [{"delta": {}, "finish_reason": "stop"}]}
        yield f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n".encode()


requests: list[dict] = []


async def fake_model(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    requests.append(body)
    if request.headers.get("authorization") != "Bearer echochat-browser-test-key":
        return httpx.Response(401, json={"error": {"message": "Invalid API key"}})
    prompt = body["messages"][-1]["content"]
    reasoning = (
        ["先理解问题。\n", "再整理答案。<img src=x onerror=alert(1)>\n" + "长文本" * 80]
        if body["thinking"]["type"] == "enabled"
        else []
    )
    latest_user = next((message["content"] for message in reversed(body["messages"])
                        if message["role"] == "user"), "")
    if "[agent]" in latest_user and body.get("tools"):
        previous = body["messages"][-1]
        if previous["role"] == "user":
            name, arguments, identifier = "calculate", {"expression": "0.1+0.2"}, "browser_calc"
        elif "result" in json.loads(previous["content"]):
            name, arguments, identifier = "create_file", {
                "name": "计算结果", "format": "md", "content": "# 结果\n0.3"
            }, "browser_file"
        else:
            return httpx.Response(200, stream=ModelStream(["已生成文件。", "计算结果为 0.3。"], 0.15))
        tool_call = {"index": 0, "id": identifier, "type": "function", "function": {
            "name": name, "arguments": json.dumps(arguments, ensure_ascii=False)
        }}
        chunks = [{"choices": [{"delta": {"tool_calls": [tool_call]}, "finish_reason": None}]},
                  {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}]
        return httpx.Response(200, text="".join(f"data: {json.dumps(chunk)}\n\n"
                                              for chunk in chunks) + "data: [DONE]\n\n")
    if "[fail]" in prompt:
        return httpx.Response(429, json={"error": {"message": "Test rate limit"}})
    if "[burst]" in prompt or "[burst-hold]" in prompt:
        answer = "逐字显示应保持自然，已有内容始终完整保存。🙂👩‍💻🇨🇳" * 24
        return httpx.Response(
            200,
            stream=ModelStream(
                [answer],
                0.12,
                reasoning,
                finish_delay=1.8 if "[burst-hold]" in prompt else 0,
            ),
            headers={"content-type": "text/event-stream"},
        )
    if "[long-code]" in prompt or "[short-then-long]" in prompt:
        lines = [
            f"values.append({index})  # Keep the complete received code available when copying."
            for index in range(160)
        ]
        pieces = (
            ["```python\n", "\n".join(lines), "\n```\n"]
            if "[short-then-long]" in prompt
            else ["```python\n" + "\n".join(lines[:120]) + "\n", "\n".join(lines[120:]) + "\n```\n"]
        )
        return httpx.Response(
            200,
            stream=ModelStream(pieces, 0.08, reasoning),
            headers={"content-type": "text/event-stream"},
        )
    if "[stream-fail]" in prompt:
        return httpx.Response(
            200,
            stream=ModelStream(
                ["发生失败前收到的内容应完整保留。🙂" * 12],
                0.12,
                reasoning,
                fail_after_content=True,
            ),
            headers={"content-type": "text/event-stream"},
        )
    if "[reasoning-only]" in prompt:
        return httpx.Response(
            200,
            stream=ModelStream(["最终回答"], 0.12, [f"思考片段{i} " for i in range(80)]),
            headers={"content-type": "text/event-stream"},
        )
    if "[slow]" in prompt:
        return httpx.Response(
            200,
            stream=ModelStream([f"片段{i} " for i in range(80)], 0.12, reasoning),
            headers={"content-type": "text/event-stream"},
        )
    answer = (
        "**模拟回答**\n\n已收到本次消息。\n\n"
        "```python\nprint('echochat')\n```\n\n"
        '<img src=x onerror="window.__unsafeHtmlExecuted=true">'
    )
    return httpx.Response(
        200,
        stream=ModelStream(
            [answer[i : i + 11] for i in range(0, len(answer), 11)], 0.02, reasoning
        ),
        headers={"content-type": "text/event-stream"},
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="browser-", dir=RESULTS) as directory:
        app = create_app(
            database_url=f"sqlite+aiosqlite:///{Path(directory).as_posix()}/test.db",
            transport=httpx.MockTransport(fake_model),
            data_dir=directory,
            allowed_origins={
                f"http://{host}:{args.frontend_port}" for host in ("localhost", "127.0.0.1")
            },
        )

        @app.get("/api/test/requests")
        async def model_requests():
            return {"items": requests}

        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
