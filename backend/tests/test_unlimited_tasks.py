import asyncio
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from test_agent import call, final, open_chat, send, sse

from app.agent import AgentExecution, protocol_messages, tool_calls_data
from app.errors import AppError
from app.main import create_app
from app.models import Message
from app.tools import ToolError, ToolRuntime

CONTEXT = [{"role": "system", "content": "test"}, {"role": "user", "content": "work"}]


def execution(provider, execute=None, enabled=True):
    async def noop(*args, **kwargs):
        pass

    async def tool(name, arguments):
        return {"result": "2"}

    runtime = SimpleNamespace(
        message_id="mock-message",
        allowed_tools=frozenset({"calculate", "read_webpage"}),
        execute=execute or tool,
    )
    return AgentExecution(runtime, noop, noop, provider, "thinking", "fake", enabled)


class FiniteProvider:
    def __init__(self, rounds=40, batch=2):
        self.rounds, self.batch, self.requests = rounds, batch, []

    async def choices(self, messages, mode, tools, key):
        self.requests.append(messages)
        if len(self.requests) > self.rounds:
            yield {"delta": {"content": "done"}, "finish_reason": "stop"}
        else:
            yield {
                "delta": {
                    "tool_calls": [
                        call("calculate", {"expression": "1+1"}, f"c{len(self.requests)}_{i}", i)
                        for i in range(self.batch)
                    ]
                },
                "finish_reason": "tool_calls",
            }


async def test_task_crosses_old_caps_and_graph_recursion_limit(monkeypatch):
    provider = FiniteProvider()
    run = execution(provider)
    started = time.monotonic()
    # Simulate over five minutes of cumulative work, without making an individual call slow.
    clock = [1000.0]

    async def tool(*args):
        clock[0] += 10
        return {"result": "2"}

    run.runtime.execute = tool
    monkeypatch.setattr("app.agent.time", SimpleNamespace(monotonic=lambda: clock[0]))
    await run.run(CONTEXT)
    assert run.content == "done"
    prompt = provider.requests[0][0]["content"]
    assert "任务没有模型轮次、工具总次数或总时长上限" in prompt
    assert "{model_calls}" not in prompt and "预算不足" not in prompt
    assert (run.model_calls, run.tool_attempts) == (41, 80)
    assert clock[0] - 1000 == 800
    assert len(protocol_messages(run.steps)) == 121
    print(
        "MOCK_METRIC "
        + json.dumps(
            {
                "scenario": "cross_old_caps",
                "mocked": True,
                "model_calls": run.model_calls,
                "tool_calls": run.tool_attempts,
                "virtual_elapsed_seconds": 800,
                "elapsed_seconds": time.monotonic() - started,
            }
        )
    )


async def test_each_model_call_has_a_hard_deadline(monkeypatch):
    class Hanging:
        async def choices(self, *args):
            while True:
                yield {"delta": {"content": "x"}}
                await asyncio.sleep(0.005)

    monkeypatch.setattr("app.agent.MODEL_TIMEOUT_SECONDS", 0.025)
    run = execution(Hanging())
    with pytest.raises(TimeoutError):
        await run.run(CONTEXT)
    assert run.model_calls == 1 and run.content


async def test_each_tool_call_times_out_and_model_can_finish(monkeypatch):
    async def hang(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr("app.agent.TOOL_TIMEOUT_SECONDS", 0.01)
    run = execution(FiniteProvider(rounds=1, batch=1), hang)
    await run.run(CONTEXT)
    assert run.content == "done"
    assert tool_calls_data(run.steps)[0]["status"] == "failed"


async def test_failed_identical_args_stop_without_reexecution():
    executed = []

    async def fail(*args):
        executed.append(args)
        raise ToolError("mock failure")

    run = execution(FiniteProvider(batch=1), fail)
    with pytest.raises(AppError) as error:
        await run.run(CONTEXT)
    assert error.value.code == "AGENT_NO_PROGRESS"
    assert len(executed) == 1 and run.tool_attempts == 2


async def test_deep_json_failure_records_signature_without_unbound_error():
    class Deep:
        async def choices(self, *args):
            value = call("calculate", {})
            value["function"]["arguments"] = "[" * 2000 + "0" + "]" * 2000
            yield {"delta": {"tool_calls": [value]}, "finish_reason": "tool_calls"}

    async def fail(*args):
        raise ToolError("invalid arguments")

    run = execution(Deep(), fail)
    with pytest.raises(AppError) as error:
        await run.run(CONTEXT)
    assert error.value.code == "AGENT_NO_PROGRESS"
    assert run.tool_attempts == 2


@pytest.mark.parametrize(
    "delta,finish,code",
    [
        ({"content": "x" * 500001}, "stop", "OUTPUT_LIMIT"),
        (
            {"tool_calls": [call("calculate", {}, index=48)]},
            "tool_calls",
            "INVALID_UPSTREAM_STREAM",
        ),
        (
            {"tool_calls": [call("calculate", {"expression": "x" * 100001})]},
            "tool_calls",
            "INVALID_UPSTREAM_STREAM",
        ),
    ],
)
async def test_output_and_single_response_parse_bounds_remain(delta, finish, code):
    class Malformed:
        async def choices(self, *args):
            yield {"delta": delta, "finish_reason": finish}

    run = execution(Malformed())
    with pytest.raises(AppError) as error:
        await run.run(CONTEXT)
    assert error.value.code == code and run.tool_attempts == 0


async def test_disabled_tools_still_reject_model_calls():
    run = execution(FiniteProvider(), enabled=False)
    with pytest.raises(AppError) as error:
        await run.run(CONTEXT)
    assert error.value.code == "INVALID_TOOL_CALLS" and run.tool_attempts == 0


async def test_completes_attachment_two_official_docs_calculation_markdown(
    tmp_path,
    monkeypatch,
):
    urls = [
        "https://docs.python.org/3/library/decimal.html",
        "https://www.sqlite.org/lang_select.html",
    ]
    requests = []
    attachment_id = None
    markdown = "# Evidence\nAttachment target: 30\nCalculation: 30\n" + "\n".join(urls)

    async def page(url, client):
        assert url in urls
        return {
            "url": url,
            "text": "Mock official documentation body",
            "truncated": False,
            "coverage": "main: extracted text",
        }

    monkeypatch.setattr("app.tools.read_public_page", page)

    def model(request):
        nonlocal attachment_id
        body = json.loads(request.content)
        requests.append(body)
        number = len(requests)
        assert body.get("tools")
        if number == 2:
            attachment_id = json.loads(body["messages"][-1]["content"])["attachments"][0]["id"]
        actions = {
            1: ("list_attachments", {}),
            2: ("read_attachment", {"attachment_id": attachment_id}),
            3: ("read_webpage", {"url": urls[0]}),
            4: ("read_webpage", {"url": urls[1]}),
            5: ("calculate", {"expression": "(10 + 5) * 2"}),
            6: ("read_webpage", {"url": urls[0]}),
            7: ("create_file", {"name": "evidence", "format": "md", "content": markdown}),
        }
        if number == 8:
            assert json.loads(body["messages"][-1]["content"])["artifact_id"]
            return httpx.Response(200, text=sse({"content": markdown + "\nSaved evidence.md"}))
        name, args = actions[number]
        return httpx.Response(
            200, text=sse({"tool_calls": [call(name, args, f"step{number}")]}, finish="tool_calls")
        )

    app = create_app(data_dir=tmp_path, transport=httpx.MockTransport(model))
    started = time.monotonic()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
        ) as api,
    ):
        cid = await open_chat(api)
        result = final(
            await send(
                api,
                cid,
                text="Use attachment and two official docs; calculate and save Markdown.",
                files={"files": ("target.txt", b"Target: (10 + 5) * 2", "text/plain")},
            )
        )
        message = result["message"]
        assert message["status"] == "completed"
        assert len(message["tool_calls"]) == 7
        assert all(item["status"] == "completed" for item in message["tool_calls"])
        assert message["tool_calls"][4]["result"]["result"] == "30"
        assert all(url in message["content"] for url in urls)
        assert len(message["artifacts"]) == 1
        assert (await api.get(message["artifacts"][0]["download_url"])).text == markdown
        run = (await api.get(f"/api/runs/{result['run_id']}")).json()
        assert run["checkpoint"]["model_calls"] == 8
        assert run["checkpoint"]["tool_calls"] == 7
        assert "budgets" not in run["task"]
        assert len(requests) == 8
        print(
            "MOCK_METRIC "
            + json.dumps(
                {
                    "scenario": "attachment_two_official_docs_calculation_markdown",
                    "mocked": True,
                    "model_calls": 8,
                    "tool_calls": 7,
                    "elapsed_seconds": round(time.monotonic() - started, 6),
                }
            )
        )


async def test_long_task_cancel_preserves_partial_protocol_artifact_and_replay(
    tmp_path, monkeypatch
):
    entered = asyncio.Event()
    execute = ToolRuntime.execute
    requests = []

    async def tool(self, name, arguments):
        if len(requests) == 35:
            entered.set()
            await asyncio.Event().wait()
        return await execute(self, name, arguments)

    monkeypatch.setattr(ToolRuntime, "execute", tool)

    def model(request):
        requests.append(json.loads(request.content))
        n = len(requests)
        action = (
            call("create_file", {"name": "partial", "format": "txt", "content": "saved"})
            if n == 1
            else call("calculate", {"expression": "1+1"}, f"call{n}")
        )
        return httpx.Response(
            200, text=sse({"content": f"Step {n}. "}, {"tool_calls": [action]}, finish="tool_calls")
        )

    app = create_app(data_dir=tmp_path, transport=httpx.MockTransport(model))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
        ) as api,
    ):
        cid, rid = await open_chat(api), str(uuid4())
        task = asyncio.create_task(send(api, cid, rid=rid))
        await asyncio.wait_for(entered.wait(), 15)
        saved = (await api.post(f"/api/generations/{rid}/cancel")).json()["message"]
        result = final(await task)
        assert result["message"] == saved and saved["status"] == "cancelled"
        assert len(saved["tool_calls"]) == 35
        assert [x["status"] for x in saved["tool_calls"]] == ["completed"] * 34 + ["cancelled"]
        assert saved["content"].startswith("Step 1.") and "Step 35." in saved["content"]
        assert len(saved["artifacts"]) == 1
        assert (await api.get(saved["artifacts"][0]["download_url"])).text == "saved"
        replay = final(await send(api, cid, rid=rid))
        assert replay["message"] == saved and len(requests) == 35
        run = (await api.get(f"/api/runs/{result['run_id']}")).json()
        assert run["state"] == "cancelled"
        assert run["checkpoint"]["model_calls"] == run["checkpoint"]["tool_calls"] == 35
        async with app.state.chats.db.sessions() as session:
            message = await session.get(Message, saved["id"])
            assert_closed(protocol_messages(message.agent_steps))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
        ) as api,
    ):
        assert (await api.get(f"/api/messages/{saved['id']}")).json() == saved


async def test_duplicate_failure_preserves_saved_artifact_and_accurate_failed_state(tmp_path):
    requests = []

    def model(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 3:
            assert "error" in json.loads(body["messages"][-1]["content"])
        action = (
            call("create_file", {"name": "partial", "format": "txt", "content": "saved"})
            if len(requests) == 1
            else call("calculate", {"expression": "unsupported"}, f"bad{len(requests)}")
        )
        return httpx.Response(
            200,
            text=sse(
                {"content": "partial evidence. "}, {"tool_calls": [action]}, finish="tool_calls"
            ),
        )

    app = create_app(data_dir=tmp_path, transport=httpx.MockTransport(model))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
        ) as api,
    ):
        cid, rid = await open_chat(api), str(uuid4())
        result = final(await send(api, cid, rid=rid))
        saved = result["message"]
        assert result["code"] == saved["error_code"] == "AGENT_NO_PROGRESS"
        assert saved["status"] == "failed" and "尚未完成" in saved["error_message"]
        assert saved["content"] == "partial evidence. " * 3
        assert (await api.get(saved["artifacts"][0]["download_url"])).text == "saved"
        run = (await api.get(f"/api/runs/{result['run_id']}")).json()
        assert run["state"] == "failed" and run["error_code"] == "AGENT_NO_PROGRESS"
        assert final(await send(api, cid, rid=rid))["message"] == saved
        assert len(requests) == 3


def assert_closed(messages):
    pending = set()
    for message in messages:
        if message["role"] == "assistant":
            assert not pending
            pending.update(x["id"] for x in message.get("tool_calls", []))
        elif message["role"] == "tool":
            pending.remove(message["tool_call_id"])
        else:
            assert not pending
    assert not pending


async def test_model_deadline_persists_truthful_request_timeout(tmp_path, monkeypatch):
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield sse({"content": "partial"}, finish="stop").split("data: [DONE]")[0].encode()
            await asyncio.Event().wait()

    monkeypatch.setattr("app.agent.MODEL_TIMEOUT_SECONDS", 0.025)
    app = create_app(
        data_dir=tmp_path,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=SlowStream())),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
        ) as api,
    ):
        result = final(await send(api, await open_chat(api)))
        assert result["code"] == "UPSTREAM_TIMEOUT"
        assert result["message"]["status"] == "failed"
        assert result["message"]["content"] == "partial"
        assert "单次" in result["message"]["error_message"]
