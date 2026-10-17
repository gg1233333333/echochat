import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.agent import protocol_messages
from app.main import create_app
from app.models import Message
from app.tools import ToolRuntime


def sse(*deltas, finish="stop"):
    chunks = [{"choices": [{"delta": delta, "finish_reason": None}]} for delta in deltas]
    chunks.append({"choices": [{"delta": {}, "finish_reason": finish}]})
    return "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"


def call(name, args, identifier="call_1", index=0):
    return {
        "index": index,
        "id": identifier,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def final(response):
    assert response.status_code == 200, response.text
    return json.loads(
        [line[6:] for line in response.text.splitlines() if line.startswith("data: ")][-1]
    )


async def open_chat(api):
    await api.put("/api/credentials/deepseek", json={"api_key": "fake-agent-key"})
    return (await api.post("/api/conversations", json={})).json()["id"]


async def send(api, cid, text="请执行任务", rid=None, **kwargs):
    return await api.post(
        f"/api/conversations/{cid}/messages",
        data={
            "text": text,
            "mode": "thinking",
            "request_id": rid or str(uuid4()),
            "agent_enabled": "true",
        },
        **kwargs,
    )


async def test_fragmented_tools_roundtrip_history_files_and_idempotency(tmp_path):
    requests = []
    split = call("calculate", {"expression": "0.1 + 0.2"})
    first, tail = split["function"]["arguments"][:8], split["function"]["arguments"][8:]

    def model(request):
        body = json.loads(request.content)
        requests.append(body)
        index = len(requests)
        if index == 1:
            split["function"]["arguments"] = first
            stream = sse(
                {"reasoning_content": "先精确计算。"},
                {"tool_calls": [split]},
                {"tool_calls": [{"index": 0, "function": {"arguments": tail}}]},
                finish="tool_calls",
            )
        elif index == 2:
            assert body["messages"][-2]["reasoning_content"] == "先精确计算。"
            assert json.loads(body["messages"][-1]["content"])["result"] == "0.3"
            stream = sse(
                {"reasoning_content": "再生成文件。"},
                {
                    "tool_calls": [
                        call(
                            "create_file",
                            {"name": "报告", "format": "md", "content": "# 结果\n0.3"},
                            "call_2",
                        )
                    ]
                },
                finish="tool_calls",
            )
        else:
            stream = sse(
                {"reasoning_content": "已检查结果。"}, {"content": "文件已生成，结果为 0.3。"}
            )
        return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"})

    app = create_app(data_dir=tmp_path, transport=httpx.MockTransport(model))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as api,
    ):
        cid = await open_chat(api)
        rid = str(uuid4())
        response = await send(api, cid, rid=rid)
        message = final(response)["message"]
        assert message["status"] == "completed", final(response)
        assert [c["status"] for c in message["tool_calls"]] == ["completed", "completed"]
        assert "event: tools" in response.text and "event: delta" in response.text
        artifact = message["artifacts"][0]
        download = await api.get(artifact["download_url"])
        assert download.text == "# 结果\n0.3"
        assert download.headers["content-disposition"].startswith("attachment;")
        saved = (await api.get(f"/api/messages/{message['id']}")).json()
        assert saved["tool_calls"] == message["tool_calls"]
        assert saved["artifacts"] == message["artifacts"]
        assert final(await send(api, cid, rid=rid))["message"] == message
        assert len(requests) == 3
        final(await send(api, cid, text="继续"))
        history = requests[-1]["messages"]
        assert [m["role"] for m in history] == [
            "system",
            "user",
            "assistant",
            "tool",
            "assistant",
            "tool",
            "assistant",
            "user",
        ]
        assert all("reasoning_content" in m for m in history if m["role"] == "assistant")
        assert "fake-agent-key" not in json.dumps(saved)
        await api.delete(f"/api/conversations/{cid}")
        assert (await api.get(artifact["download_url"])).status_code == 404
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as api,
    ):
        assert (await api.get("/api/credentials/deepseek")).json() == {"configured": False}


async def test_cancel_during_tool_and_restart_preserve_trace(tmp_path, monkeypatch):
    entered = asyncio.Event()

    async def slow_tool(self, name, arguments):
        entered.set()
        await asyncio.sleep(60)

    monkeypatch.setattr(ToolRuntime, "execute", slow_tool)
    app = create_app(
        data_dir=tmp_path,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=sse(
                    {"tool_calls": [call("calculate", {"expression": "1+1"})]}, finish="tool_calls"
                ),
            )
        ),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as api,
    ):
        cid, rid = await open_chat(api), str(uuid4())
        pending = asyncio.create_task(send(api, cid, rid=rid))
        await asyncio.wait_for(entered.wait(), 3)
        cancelled = (await api.post(f"/api/generations/{rid}/cancel")).json()["message"]
        assert cancelled["status"] == "cancelled"
        assert cancelled["tool_calls"][0]["status"] == "cancelled"
        assert final(await pending)["message"]["status"] == "cancelled"
        mid = cancelled["id"]
        # Emulate an abrupt restart after a persisted running tool snapshot.
        async with app.state.chats.db.sessions.begin() as session:
            message = await session.get(Message, mid)
            message.status = "generating"
            message.agent_steps = [
                {**message.agent_steps[0], "tools": [{"status": "running", "result": None}]}
            ]
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as api,
    ):
        saved = (await api.get(f"/api/messages/{mid}")).json()
        assert saved["status"] == "interrupted"
        assert saved["tool_calls"][0]["status"] == "interrupted"
        async with app.state.chats.db.sessions() as session:
            message = await session.scalar(select(Message).where(Message.id == mid))
            protocol = protocol_messages(message.agent_steps)
            assert [item["role"] for item in protocol] == ["assistant", "tool"]
            assert "error" in json.loads(protocol[-1]["content"])


async def test_attachments_are_scoped_and_free_search_and_web_results_reach_model(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "app.tools.search_web",
        lambda query: {
            "results": [{"title": "Example", "url": "https://example.com", "snippet": query}]
        },
    )

    async def page(url, client):
        return {"url": url, "text": "Public text", "truncated": False}

    monkeypatch.setattr("app.tools.read_public_page", page)
    requests = []

    def model(request):
        body = json.loads(request.content)
        requests.append(body)
        last = body["messages"][-1]
        if last["role"] == "user":
            name, args = "list_attachments", {}
        else:
            result = json.loads(last["content"])
            if "attachments" in result:
                assert len(result["attachments"]) == 1
                name, args = "read_attachment", {"attachment_id": result["attachments"][0]["id"]}
            elif "name" in result:
                assert result["text"] == "private attachment text"
                name, args = "search_web", {"query": "public query"}
            elif "results" in result:
                name, args = "read_webpage", {"url": result["results"][0]["url"]}
            else:
                assert result["text"] == "Public text"
                return httpx.Response(200, text=sse({"content": "整理完成"}))
        return httpx.Response(
            200,
            text=sse(
                {"tool_calls": [call(name, args, f"call_{len(requests)}")]}, finish="tool_calls"
            ),
        )

    app = create_app(data_dir=tmp_path, transport=httpx.MockTransport(model))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as api,
    ):
        cid = await open_chat(api)
        result = final(
            await send(
                api, cid, files={"files": ("notes.txt", b"private attachment text", "text/plain")}
            )
        )
        assert result["message"]["status"] == "completed"
        aid = result["message"]["tool_calls"][0]["result"]["attachments"][0]["id"]
        other = (await api.post("/api/conversations", json={})).json()
        runtime = ToolRuntime(app.state.chats.db, None, other["id"], "unused", "other-segment", 9)
        from app.tools import ToolError

        with pytest.raises(ToolError):
            await runtime.execute("read_attachment", json.dumps({"attachment_id": aid}))


async def test_stopped_final_answer_remains_in_next_model_context(tmp_path):
    received = asyncio.Event()
    calls = []

    class Partial(httpx.AsyncByteStream):
        async def __aiter__(self):
            chunk = {"choices": [{"delta": {"content": "已计算，下一步"}}]}
            yield f"data: {json.dumps(chunk)}\n\n".encode()
            received.set()
            await asyncio.Event().wait()

    def model(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(
                200,
                text=sse(
                    {"tool_calls": [call("calculate", {"expression": "1+1"})]}, finish="tool_calls"
                ),
            )
        if len(calls) == 2:
            return httpx.Response(200, stream=Partial())
        return httpx.Response(200, text=sse({"content": "继续回答"}))

    app = create_app(data_dir=tmp_path, transport=httpx.MockTransport(model))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as api,
    ):
        cid, rid = await open_chat(api), str(uuid4())
        pending = asyncio.create_task(send(api, cid, rid=rid))
        await asyncio.wait_for(received.wait(), 3)
        await api.post(f"/api/generations/{rid}/cancel")
        assert final(await pending)["message"]["content"] == "已计算，下一步"
        final(await send(api, cid, text="继续"))
        assert calls[-1]["messages"][-2]["content"] == "已计算，下一步"


async def test_disabled_tools_never_execute_an_upstream_tool_call(tmp_path, monkeypatch):
    executed = []

    async def tool(self, name, arguments):
        executed.append(name)
        return {"result": "2"}

    monkeypatch.setattr(ToolRuntime, "execute", tool)

    def model(request):
        assert "tools" not in json.loads(request.content)
        return httpx.Response(
            200,
            text=sse(
                {"tool_calls": [call("calculate", {"expression": "1+1"})]}, finish="tool_calls"
            ),
        )

    app = create_app(data_dir=tmp_path, transport=httpx.MockTransport(model))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as api,
    ):
        cid = await open_chat(api)
        result = final(
            await api.post(
                f"/api/conversations/{cid}/messages",
                data={
                    "text": "不要调用工具",
                    "mode": "thinking",
                    "request_id": str(uuid4()),
                    "agent_enabled": "false",
                },
            )
        )
        assert result["code"] == "INVALID_TOOL_CALLS"
        assert executed == []


async def test_cancel_preserves_completed_file_and_regenerate_removes_it(tmp_path, monkeypatch):
    entered = asyncio.Event()
    execute = ToolRuntime.execute
    requests = []

    async def tool(self, name, arguments):
        if name == "calculate":
            entered.set()
            await asyncio.Event().wait()
        return await execute(self, name, arguments)

    monkeypatch.setattr(ToolRuntime, "execute", tool)

    def model(request):
        requests.append(json.loads(request.content))
        if len(requests) > 1:
            return httpx.Response(200, text=sse({"content": "重新回答"}))
        calls = [
            call("create_file", {"name": "保留结果", "format": "txt", "content": "saved"}),
            call("calculate", {"expression": "1+1"}, "slow_call", 1),
        ]
        return httpx.Response(200, text=sse({"tool_calls": calls}, finish="tool_calls"))

    app = create_app(data_dir=tmp_path, transport=httpx.MockTransport(model))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as api,
    ):
        cid, rid = await open_chat(api), str(uuid4())
        pending = asyncio.create_task(send(api, cid, rid=rid))
        await asyncio.wait_for(entered.wait(), 3)
        saved = (await api.post(f"/api/generations/{rid}/cancel")).json()["message"]
        assert final(await pending)["message"] == saved
        assert [c["status"] for c in saved["tool_calls"]] == ["completed", "cancelled"]
        download_url = saved["artifacts"][0]["download_url"]
        assert (await api.get(download_url)).text == "saved"
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as api,
    ):
        assert (await api.get(download_url)).text == "saved"
        await open_chat(api)
        regenerated = final(
            await api.post(
                f"/api/messages/{saved['id']}/regenerate",
                json={"request_id": str(uuid4()), "mode": "thinking", "agent_enabled": True},
            )
        )
        assert regenerated["message"]["status"] == "completed"
        assert regenerated["message"]["artifacts"] == []
        assert (await api.get(download_url)).status_code == 404
