import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from starlette.requests import ClientDisconnect

from app.main import GenerationResponse, create_app
from app.models import Attachment, Conversation, Message


def request_id():
    return str(uuid4())


def upstream_reply(text="answer", reason="stop", reasoning=""):
    chunks = [
        {
            "choices": [
                {
                    "delta": {"reasoning_content": reasoning[:3], "content": None},
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {"content": text, "reasoning_content": reasoning[3:]},
                    "finish_reason": None,
                }
            ]
        },
        {"choices": [{"delta": {}, "finish_reason": reason}]},
    ]
    return "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"


def events(response):
    assert response.status_code == 200, response.text
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


@pytest.fixture
async def client(tmp_path):
    calls = []

    def upstream(request):
        calls.append(json.loads(request.content))
        if calls[-1]["messages"][-1]["content"] == "reject":
            return httpx.Response(401, json={"error": {"message": "a secret upstream message"}})
        return httpx.Response(
            200,
            text=upstream_reply(
                reasoning=(
                    "先理解问题，再给出回答。" if calls[-1]["thinking"]["type"] == "enabled" else ""
                )
            ),
            headers={"Content-Type": "text/event-stream"},
        )

    app = create_app(data_dir=tmp_path, transport=httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as api:
            api.app = app
            api.calls = calls
            yield api


async def setup_chat(client):
    assert (
        await client.put("/api/credentials/deepseek", json={"api_key": "test-secret"})
    ).json() == {"configured": True}
    return (await client.post("/api/conversations", json={})).json()


async def send(client, conversation, text="hello", mode="thinking", rid=None):
    return await client.post(
        f"/api/conversations/{conversation['id']}/messages",
        data={"text": text, "mode": mode, "request_id": rid or request_id()},
    )


async def test_key_privacy_host_origin_and_validation(client):
    assert (await client.get("/api/credentials/deepseek")).json() == {"configured": False}
    conversation = (await client.post("/api/conversations", json={})).json()
    assert (await send(client, conversation)).json()["detail"]["code"] == "API_KEY_REQUIRED"
    secret = "invalid\nsecret"
    response = await client.put("/api/credentials/deepseek", json={"api_key": secret})
    assert response.status_code == 422 and "secret" not in response.text
    assert (
        await client.get("/api/options", headers={"Origin": "https://evil.example"})
    ).status_code == 403
    assert (await client.get("/api/options", headers={"Host": "evil.example"})).status_code == 403
    assert (
        await client.get("/api/options", headers={"Origin": "http://localhost:5173"})
    ).status_code == 200
    response = await client.post("/api/conversations", json={"role_id": {"key": secret}})
    assert response.status_code == 422 and "secret" not in response.text


async def test_conversation_stable_ids_empty_reuse_and_duplicate_titles(client):
    first = await setup_chat(client)
    assert (await client.post("/api/conversations", json={})).json()["id"] == first["id"]
    assert (await client.get("/api/conversations")).json()["items"] == []
    events(await send(client, first))
    second = (await client.post("/api/conversations", json={})).json()
    assert first["id"] != second["id"]
    for conversation in (first, second):
        renamed = await client.patch(
            f"/api/conversations/{conversation['id']}", json={"title": "same"}
        )
        assert renamed.json()["title"] == "same"
    items = (await client.get("/api/conversations", params={"include_empty": True})).json()["items"]
    assert len(items) == 2


async def test_unified_assistant_automatic_and_manual_titles(client):
    options = (await client.get("/api/options")).json()
    assert [role["id"] for role in options["roles"]] == ["general"]
    assert [item["label"] for item in options["modes"]] == ["深度思考", "快速回答"]
    conversation = await setup_chat(client)
    first = events(await send(client, conversation, text="如何 **使用 FastAPI**？"))
    assert first[0]["conversation"]["title"] == "如何 使用 FastAPI？"
    assert first[-1]["conversation"]["title"] == first[0]["conversation"]["title"]
    assert "拒绝" not in client.calls[-1]["messages"][0]["content"]
    later = events(await send(client, conversation, text="还有一个问题"))
    assert later[-1]["conversation"]["title"] == first[0]["conversation"]["title"]
    manual = (await client.post("/api/conversations", json={})).json()
    await client.patch(f"/api/conversations/{manual['id']}", json={"title": "新对话"})
    result = events(await send(client, manual, text="保留手动标题"))
    assert result[-1]["conversation"]["title"] == "新对话"
    files = (await client.post("/api/conversations", json={})).json()
    uploaded = await client.post(
        f"/api/conversations/{files['id']}/messages",
        data={"mode": "thinking", "request_id": request_id()},
        files={"files": ("main.py", b"print(1)", "text/plain")},
    )
    assert events(uploaded)[-1]["conversation"]["title"] == "附件：main.py"


async def test_generation_persistence_idempotency_modes_and_error(client):
    conversation = await setup_chat(client)
    rid = request_id()
    result = events(await send(client, conversation, rid=rid))
    assert result[-1]["message"]["status"] == "completed"
    assert result[-1]["message"]["content"] == "answer"
    assert result[-1]["message"]["reasoning_content"] == "先理解问题，再给出回答。"
    deltas = [item for item in result if "message_id" in item]
    assert "".join(item["reasoning_content"] for item in deltas) == "先理解问题，再给出回答。"
    assert "".join(item["content"] for item in deltas) == "answer"
    history = (await client.get(f"/api/conversations/{conversation['id']}/messages")).json()[
        "items"
    ]
    assert history[-1]["reasoning_content"] == result[-1]["message"]["reasoning_content"]
    assert history[0]["reasoning_content"] == ""
    assert client.calls[0]["model"] == "deepseek-flash"
    assert client.calls[0]["thinking"] == {"type": "enabled"}
    replay = events(await send(client, conversation, rid=rid))
    assert replay[-1]["message"]["reasoning_content"] == history[-1]["reasoning_content"]
    assert len(client.calls) == 1
    second = (await client.post("/api/conversations", json={})).json()
    assert (await send(client, second, rid=rid)).status_code == 409
    failed = events(await send(client, conversation, text="reject", mode="non-thinking"))[-1]
    assert failed["message"]["status"] == "failed"
    assert failed["message"]["content"] == ""
    assert failed["code"] == "INVALID_API_KEY"
    assert client.calls[-1]["thinking"] == {"type": "disabled"}
    events(await send(client, conversation, text="next"))
    assert all(item["content"] for item in client.calls[-1]["messages"])
    assert all("reasoning_content" not in item for item in client.calls[-1]["messages"])
    assert "secret upstream" not in json.dumps(client.calls[-1])
    plain = events(await send(client, conversation, text="quick", mode="non-thinking"))[-1]
    assert plain["message"]["reasoning_content"] == ""


async def test_regenerate_original_segment_and_truncation_after_merging_roles(client):
    conversation = await setup_chat(client)
    first = events(await send(client, conversation, text="original"))[-1]["message"]
    async with client.app.state.chats.db.sessions.begin() as session:
        saved = await session.get(Conversation, conversation["id"])
        saved.context_segment = "later-segment"
    events(await send(client, conversation, text="python"))
    assert [item["content"] for item in client.calls[-1]["messages"][1:]] == ["python"]
    response = await client.post(
        f"/api/messages/{first['id']}/regenerate",
        json={"request_id": request_id(), "mode": "non-thinking"},
    )
    final = events(response)[-1]
    assert final["conversation"]["current_role_id"] == "general"
    assert final["message"]["context_segment"] == first["context_segment"]
    assert [item["content"] for item in client.calls[-1]["messages"][1:]] == ["original"]
    messages = (await client.get(f"/api/conversations/{conversation['id']}/messages")).json()[
        "items"
    ]
    assert len(messages) == 2
    assert messages[-1]["seq"] > first["seq"]
    assert (await client.get(f"/api/messages/{first['id']}")).status_code == 404
    await client.delete(f"/api/messages/{messages[0]['id']}")
    remaining = (await client.get(f"/api/messages/{messages[-1]['id']}")).json()
    assert remaining["related_user_message_id"] is None
    retry = await client.post(
        f"/api/messages/{remaining['id']}/regenerate",
        json={"request_id": request_id(), "mode": "thinking"},
    )
    assert retry.status_code == 409


async def test_attachment_import_idempotency_and_pagination(client):
    conversation = await setup_chat(client)
    response = await client.post(
        f"/api/conversations/{conversation['id']}/messages",
        data={"text": "file", "mode": "thinking", "request_id": request_id()},
        files={"files": ("example.vue", b"x" * 9000, "application/octet-stream")},
    )
    started = events(response)[0]
    attachment = started["user_message"]["attachments"][0]
    assert len(attachment["extracted_text"]) == 8000 and attachment["truncated"]
    assert "x" * 8000 in client.calls[-1]["messages"][-1]["content"]
    page = (await client.get(f"/api/conversations/{conversation['id']}/messages?limit=1")).json()
    assert page["has_more"] and len(page["items"]) == 1
    old = (
        await client.get(
            f"/api/conversations/{conversation['id']}/messages",
            params={"before_seq": page["items"][0]["seq"]},
        )
    ).json()
    assert old["items"][0]["role"] == "user"
    snapshot = {
        "session": {
            "old": [
                {"role": "user", "content": "old question"},
                {"role": "assistant", "content": "old answer"},
            ]
        },
        "roleContextStart": {"old": 0},
        "sessionRoles": {"old": "general"},
    }
    imported = await client.post("/api/import/local-history", json={"snapshot": snapshot})
    assert imported.json()["imported_messages"] == 2
    imported = await client.post("/api/import/local-history", json={"snapshot": snapshot})
    assert imported.json()["skipped_conversations"] == 1
    items = (await client.get("/api/conversations")).json()["items"]
    imported_conversation = next(item for item in items if item["title"] == "old")
    old_messages = (
        await client.get(f"/api/conversations/{imported_conversation['id']}/messages")
    ).json()["items"]
    assert all(item["created_at"] is None and item["mode"] is None for item in old_messages)


class BlockingStream(httpx.AsyncByteStream):
    def __init__(self):
        self.first = asyncio.Event()
        self.closed = asyncio.Event()

    async def __aiter__(self):
        yield (
            b'data: {"choices":[{"delta":{"reasoning_content":"partial reasoning"},'
            b'"finish_reason":null}]}\n\n'
        )
        yield b'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}\n\n'
        self.first.set()
        await asyncio.Event().wait()

    async def aclose(self):
        self.closed.set()


@pytest.mark.parametrize("terminal_status", ["completed", "cancelled"])
async def test_import_rejected_during_generation_preserves_stream(tmp_path, terminal_status):
    class ImportStream(BlockingStream):
        def __init__(self):
            super().__init__()
            self.continue_stream = asyncio.Event()
            self.checkpointed = asyncio.Event()
            self.finish = asyncio.Event()

        async def __aiter__(self):
            yield (
                b'data: {"choices":[{"delta":{"content":"partial",'
                b'"reasoning_content":"partial reasoning"}}]}\n\n'
            )
            self.first.set()
            await self.continue_stream.wait()
            await asyncio.sleep(1.1)
            yield (
                b'data: {"choices":[{"delta":{"content":" continued",'
                b'"reasoning_content":" continued"}}]}\n\n'
            )
            self.checkpointed.set()
            await self.finish.wait()
            yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            yield b"data: [DONE]\n\n"

    stream = ImportStream()
    app = create_app(
        data_dir=tmp_path,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://localhost:8000"
        ) as api:
            conversation = await setup_chat(api)
            rid = request_id()
            generation = asyncio.create_task(send(api, conversation, text="slow", rid=rid))
            try:
                await asyncio.wait_for(stream.first.wait(), timeout=3)
                snapshot = {"session": {"imported": [{"role": "user", "content": "old"}]}}
                imported = await api.post("/api/import/local-history", json={"snapshot": snapshot})
                assert imported.status_code == 409
                assert imported.json()["detail"]["code"] == "GENERATION_BUSY"
                assert not generation.done() and not stream.closed.is_set()
                conversations = (await api.get("/api/conversations")).json()["items"]
                assert [item["id"] for item in conversations] == [conversation["id"]]

                stream.continue_stream.set()
                await asyncio.wait_for(stream.checkpointed.wait(), timeout=3)
                messages = (
                    await api.get(f"/api/conversations/{conversation['id']}/messages")
                ).json()["items"]
                checkpoint = messages[-1]
                assert checkpoint["status"] == "generating"
                assert checkpoint["content"] == "partial continued"
                assert checkpoint["reasoning_content"] == "partial reasoning continued"
                if terminal_status == "cancelled":
                    cancelled = await asyncio.wait_for(
                        api.post(f"/api/generations/{rid}/cancel"), timeout=3
                    )
                    assert cancelled.json()["message"]["status"] == "cancelled"
                else:
                    stream.finish.set()
                terminal = events(await asyncio.wait_for(generation, timeout=3))[-1]
                assert terminal["message"]["status"] == terminal_status
                assert terminal["message"]["content"] == checkpoint["content"]
                assert terminal["message"]["reasoning_content"] == checkpoint["reasoning_content"]
                saved = (await api.get(f"/api/messages/{checkpoint['id']}")).json()
                assert saved["status"] == terminal_status
                assert saved["content"] == checkpoint["content"]
                assert saved["reasoning_content"] == checkpoint["reasoning_content"]
                assert stream.closed.is_set()
                imported = await api.post("/api/import/local-history", json={"snapshot": snapshot})
                assert imported.status_code == 200
                assert imported.json()["imported_messages"] == 1
            finally:
                stream.continue_stream.set()
                stream.finish.set()
                await asyncio.wait_for(generation, timeout=3)


async def test_cancel_busy_context_mutation_and_delete(tmp_path):
    stream = BlockingStream()
    app = create_app(
        data_dir=tmp_path,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://localhost:8000"
        ) as api:
            conversation = await setup_chat(api)
            active = await app.state.generations.prepare(
                request_id=request_id(),
                mode="thinking",
                conversation_id=conversation["id"],
                text="slow",
            )
            await stream.first.wait()
            assert (await send(api, conversation)).status_code == 409
            assert (
                await api.patch(
                    f"/api/conversations/{conversation['id']}", json={"role_id": "developer"}
                )
            ).status_code == 422
            assert (
                await api.patch(
                    f"/api/conversations/{conversation['id']}", json={"title": "keep rename"}
                )
            ).status_code == 200
            cancelled = await api.post(f"/api/generations/{active.request_id}/cancel")
            assert cancelled.json()["message"]["status"] == "cancelled"
            assert cancelled.json()["message"]["content"] == "partial"
            assert cancelled.json()["message"]["reasoning_content"] == "partial reasoning"
            assert stream.closed.is_set()
            assert (await api.get("/api/conversations")).json()["items"][0][
                "title"
            ] == "keep rename"
            await api.delete(f"/api/conversations/{conversation['id']}")
            assert (await api.get(f"/api/messages/{active.message_id}")).status_code == 404


@pytest.mark.parametrize("clear_all", [False, True])
async def test_delete_long_history_cascades_and_preserves_other_conversations(client, clear_all):
    snapshot = {
        "session": {
            "long-delete": [
                {"role": "user" if index % 2 == 0 else "assistant", "content": "x" * 4096}
                for index in range(100)
            ],
            "preserved": [
                {"role": "user", "content": "keep question"},
                {"role": "assistant", "content": "keep answer"},
            ],
        }
    }
    response = await client.post("/api/import/local-history", json={"snapshot": snapshot})
    assert response.status_code == 200
    items = (await client.get("/api/conversations")).json()["items"]
    target = next(item for item in items if item["title"] == "long-delete")
    preserved = next(item for item in items if item["title"] == "preserved")
    messages = (await client.get(f"/api/conversations/{target['id']}/messages")).json()["items"]
    database = client.app.state.chats.db
    async with database.sessions.begin() as session:
        session.add(
            Attachment(
                message_id=messages[0]["id"],
                name="fixture.txt",
                size=4,
                mime="text/plain",
                extracted_text="file",
                status="extracted",
            )
        )
    endpoint = "/api/conversations" if clear_all else f"/api/conversations/{target['id']}"
    deleted = await client.delete(endpoint)
    assert deleted.status_code == 204
    assert (await client.get(f"/api/conversations/{target['id']}/messages")).status_code == 404
    async with database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Attachment)) == 0
        assert await session.scalar(select(func.count()).select_from(Message)) == (
            0 if clear_all else 2
        )
        assert await session.scalar(select(func.count()).select_from(Conversation)) == (
            0 if clear_all else 1
        )
    if not clear_all:
        kept = (await client.get(f"/api/conversations/{preserved['id']}/messages")).json()["items"]
        assert [item["content"] for item in kept] == ["keep question", "keep answer"]
    assert client.calls == []


async def test_cancel_during_final_save_keeps_terminal_state(client, monkeypatch):
    conversation = await setup_chat(client)
    generations = client.app.state.generations
    original = generations.final_data
    saving, release = asyncio.Event(), asyncio.Event()

    async def slow_save(*args, **kwargs):
        saving.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(generations, "final_data", slow_save)
    active = await generations.prepare(
        request_id=request_id(), mode="thinking", conversation_id=conversation["id"], text="test"
    )
    await saving.wait()
    cancellation = asyncio.create_task(generations.cancel(active.request_id))
    await asyncio.sleep(0)
    assert not cancellation.done()
    release.set()
    result = await cancellation
    assert result["message"]["status"] == "completed"
    assert active.done.is_set()


async def test_reasoning_only_is_checkpointed_cancelled_and_read_after_restart(tmp_path):
    checkpointed = asyncio.Event()

    class ReasoningStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for fragment in ("first", " second"):
                yield (
                    "data: "
                    + json.dumps({"choices": [{"delta": {"reasoning_content": fragment}}]})
                    + "\n\n"
                ).encode()
                await asyncio.sleep(1.1)
            checkpointed.set()
            await asyncio.Event().wait()

    app = create_app(
        data_dir=tmp_path,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=ReasoningStream())),
    )
    async with app.router.lifespan_context(app):
        service = app.state.generations
        service.api_key = "test-secret"
        conversation = await app.state.chats.create_conversation("general")
        active = await service.prepare(
            request_id=request_id(),
            mode="thinking",
            conversation_id=conversation["id"],
            text="test",
        )
        await asyncio.wait_for(checkpointed.wait(), timeout=5)
        snapshot = await app.state.chats.get_message(active.message_id)
        assert snapshot["status"] == "generating" and snapshot["content"] == ""
        assert snapshot["reasoning_content"] == "first second"
        terminal = (await service.cancel(active.request_id))["message"]
        assert terminal["status"] == "cancelled"
        assert terminal["reasoning_content"] == snapshot["reasoning_content"]

    restarted = create_app(data_dir=tmp_path)
    async with restarted.router.lifespan_context(restarted):
        history = await restarted.state.chats.get_messages(conversation["id"], None, 100)
        assert history["items"][-1]["reasoning_content"] == "first second"
        assert history["items"][-1]["status"] == "cancelled"


@pytest.mark.parametrize("invalid_reasoning", [0, [], {}])
async def test_invalid_reasoning_is_an_explicit_stream_error(tmp_path, invalid_reasoning):
    body = (
        "data: "
        + json.dumps({"choices": [{"delta": {"reasoning_content": invalid_reasoning}}]})
        + "\n\n"
    )
    app = create_app(
        data_dir=tmp_path,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=body)),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8000"
        ) as api:
            conversation = await setup_chat(api)
            terminal = events(await send(api, conversation))[-1]
            assert terminal["code"] == "INVALID_UPSTREAM_STREAM"
            assert terminal["message"]["reasoning_content"] == ""


async def test_startup_recovers_interrupted_without_key(tmp_path):
    app = create_app(data_dir=tmp_path)
    async with app.router.lifespan_context(app):
        conversation = await app.state.chats.create_conversation("general")
        async with app.state.chats.db.sessions.begin() as session:
            session.add(
                Message(
                    conversation_id=conversation["id"],
                    seq=1,
                    role="assistant",
                    content="saved partial",
                    role_id="general",
                    context_segment=conversation["context_segment"],
                    status="generating",
                )
            )
    app = create_app(data_dir=tmp_path)
    async with app.router.lifespan_context(app):
        async with app.state.chats.db.sessions() as session:
            message = await session.scalar(select(Message))
            assert message.status == "interrupted"
            assert message.content == "saved partial"
        assert app.state.generations.api_key is None


async def test_removed_request_cannot_generate_again_and_regenerate_replay(client):
    conversation = await setup_chat(client)
    rid = request_id()
    first = events(await send(client, conversation, rid=rid))[-1]["message"]
    regen_id = request_id()
    payload = {"request_id": regen_id, "mode": "thinking"}
    regenerated = events(await client.post(f"/api/messages/{first['id']}/regenerate", json=payload))
    assert len(client.calls) == 2
    replayed = events(await client.post(f"/api/messages/{first['id']}/regenerate", json=payload))
    assert replayed[-1]["message"]["id"] == regenerated[-1]["message"]["id"]
    assert len(client.calls) == 2
    assert (await send(client, conversation, rid=rid)).json()["detail"]["code"] == "REQUEST_REMOVED"
    replacement = regenerated[-1]["message"]
    assert (
        await client.post(f"/api/messages/{replacement['id']}/regenerate", json=payload)
    ).json()["detail"]["code"] == "REQUEST_ID_REUSED"
    await client.delete(f"/api/messages/{replacement['id']}")
    assert (await send(client, conversation, rid=regen_id)).status_code == 409
    assert len(client.calls) == 2


async def test_stream_consumer_disconnect_cancels_upstream(tmp_path):
    stream = BlockingStream()
    app = create_app(
        data_dir=tmp_path,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)),
    )
    async with app.router.lifespan_context(app):
        conversation = await app.state.chats.create_conversation("general")
        service = app.state.generations
        service.api_key = "test-secret"
        active = await service.prepare(
            request_id=request_id(),
            mode="thinking",
            conversation_id=conversation["id"],
            text="slow",
        )
        consumer = service.stream(active)
        assert "started" in await anext(consumer)
        await stream.first.wait()
        await consumer.aclose()
        await asyncio.wait_for(active.done.wait(), timeout=3)
        saved = await app.state.chats.get_message(active.message_id)
        assert saved["status"] == "cancelled" and saved["content"] == "partial"
        assert stream.closed.is_set()


async def test_request_body_limit_includes_chunked_uploads(client, monkeypatch):
    import app.main

    monkeypatch.setattr(app.main, "MAX_REQUEST_BYTES", 32)

    async def body():
        yield b'{"api_key":"'
        yield b"x" * 100
        yield b'"}'

    response = await client.put(
        "/api/credentials/deepseek", content=body(), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert (await client.get("/api/credentials/deepseek")).json() == {"configured": False}


async def test_response_send_failure_also_cancels_before_first_event(tmp_path):
    stream = BlockingStream()
    app = create_app(
        data_dir=tmp_path,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)),
    )
    async with app.router.lifespan_context(app):
        conversation = await app.state.chats.create_conversation("general")
        service = app.state.generations
        service.api_key = "test-secret"
        active = await service.prepare(
            request_id=request_id(),
            mode="thinking",
            conversation_id=conversation["id"],
            text="slow",
        )
        await stream.first.wait()

        async def disconnected_receive():
            return {"type": "http.disconnect"}

        async def failed_send(_):
            raise OSError("client closed connection")

        with pytest.raises(ClientDisconnect):
            await GenerationResponse(service, active)(
                {"type": "http", "asgi": {"spec_version": "2.4"}},
                disconnected_receive,
                failed_send,
            )
        await asyncio.wait_for(active.done.wait(), timeout=3)
        assert (await app.state.chats.get_message(active.message_id))["status"] == "cancelled"
        assert stream.closed.is_set()


@pytest.mark.parametrize(
    ("upstream_status", "body", "status", "code", "finish_reason"),
    [
        (200, upstream_reply(reason="length"), "completed", None, "length"),
        (
            200,
            'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
            "failed",
            "UPSTREAM_DISCONNECTED",
            None,
        ),
        (400, '{"error":{"code":"context_length_exceeded"}}', "failed", "CONTEXT_TOO_LONG", None),
        (200, "data: malformed\n\n", "failed", "INVALID_UPSTREAM_STREAM", None),
    ],
)
async def test_upstream_terminal_semantics(
    tmp_path, upstream_status, body, status, code, finish_reason
):
    app = create_app(
        data_dir=tmp_path,
        transport=httpx.MockTransport(lambda _: httpx.Response(upstream_status, text=body)),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://localhost:8000"
        ) as api:
            conversation = await setup_chat(api)
            message = events(await send(api, conversation))[-1]["message"]
            assert message["status"] == status
            assert message["error_code"] == code
            assert message["finish_reason"] == finish_reason
