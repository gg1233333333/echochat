import asyncio
import codecs
import json
import logging
from collections.abc import AsyncIterator

import anyio
import httpx
from starlette.responses import StreamingResponse

from .config import Settings
from .errors import ChatError, provider_error
from .schemas import ChatRequest
from .sse import SSEDecoder, event

logger = logging.getLogger(__name__)
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"


async def provider_events(
    client: httpx.AsyncClient, settings: Settings, payload: ChatRequest
) -> AsyncIterator[bytes]:
    # No user-controlled URL, headers, model or generation budget.
    async with client.stream(
        "POST",
        DEEPSEEK_URL,
        headers={
            "Authorization": f"Bearer {settings.deepseek_api_key.get_secret_value()}",
            "Accept": "text/event-stream",
        },
        json=payload.upstream_payload(settings.max_output_tokens),
    ) as response:
        if response.status_code != 200:
            # Never expose the upstream body (it may echo credentials or prompts).
            raise provider_error(response.status_code)
        if response.headers.get("content-type", "").split(";")[0] != "text/event-stream":
            raise ChatError("upstream_protocol", "模型服务未返回有效的事件流。")
        parser = SSEDecoder()
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        finish_reason = "stop"
        async for chunk in response.aiter_bytes():
            for data in parser.feed(decoder.decode(chunk)):
                if data == "[DONE]":
                    yield event("done", {"finish_reason": finish_reason})
                    return
                try:
                    item = json.loads(data)
                    if not isinstance(item, dict) or "error" in item:
                        raise ValueError("Invalid provider event")
                    choices = item.get("choices", [])
                    if not isinstance(choices, list):
                        raise ValueError("Invalid choices")
                    if not choices:  # usage-only event
                        continue
                    choice = choices[0]
                    delta = choice.get("delta", {})
                    content = delta.get("content")
                    if content is not None and not isinstance(content, str):
                        raise ValueError("Invalid content")
                    if choice.get("finish_reason"):
                        if choice["finish_reason"] not in ("stop", "length", "content_filter"):
                            raise ValueError("Invalid finish reason")
                        finish_reason = choice["finish_reason"]
                    if content:
                        yield event("delta", {"content": content})
                    # reasoning_content is deliberately not rendered as a final answer.
                except (ValueError, TypeError, AttributeError) as exc:
                    raise ChatError("upstream_protocol", "模型服务返回了无效的流事件。") from exc
        decoder.decode(b"", final=True)
        raise ChatError("upstream_truncated", "模型响应意外中断，可重新生成。", 502, True)


async def relay_events(
    client: httpx.AsyncClient, settings: Settings, payload: ChatRequest, request_id: str
) -> AsyncIterator[bytes]:
    source = provider_events(client, settings, payload)
    pending = None
    deadline = asyncio.get_running_loop().time() + settings.stream_timeout_seconds
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(anext(source))
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise ChatError("stream_timeout", "回复超过最大生成时限，请重试。", 504, True)
            completed, _ = await asyncio.wait(
                {pending}, timeout=min(settings.heartbeat_seconds, remaining)
            )
            if not completed:
                yield b": keepalive\n\n"
                continue
            try:
                value = pending.result()
            except StopAsyncIteration:
                return
            pending = None
            yield value
    except httpx.TimeoutException:
        yield event(
            "error",
            ChatError("upstream_timeout", "等待模型服务超时，请重试。", 504, True).payload(
                request_id
            ),
        )
    except httpx.HTTPError:
        yield event(
            "error",
            ChatError("upstream_network", "无法连接模型服务，请稍后重试。", 502, True).payload(
                request_id
            ),
        )
    except UnicodeError:
        yield event(
            "error",
            ChatError("upstream_protocol", "模型服务返回了无效的文本编码。").payload(request_id),
        )
    except ChatError as exc:
        logger.warning("chat_failed request_id=%s code=%s", request_id, exc.code)
        yield event("error", exc.payload(request_id))
    except Exception as exc:
        # Do not log exception values, upstream headers or request bodies.
        logger.error("chat_failed request_id=%s exception_type=%s", request_id, type(exc).__name__)
        yield event(
            "error",
            ChatError("internal_error", "对话服务内部错误，请稍后重试。", 500).payload(request_id),
        )
    finally:
        # Shield cleanup from downstream disconnect cancellation.
        with anyio.CancelScope(shield=True):
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await source.aclose()


class ManagedStreamingResponse(StreamingResponse):
    """Monitor disconnects even while waiting for upstream headers or an idle stream.

    Own and close the iterator on every ASGI exit, including a failed send. The outer
    deadline also bounds a client that stops reading without disconnecting.
    """

    def __init__(self, body, *, total_timeout: float, **kwargs):
        super().__init__(body, **kwargs)
        self.total_timeout = total_timeout

    async def __call__(self, scope, receive, send):
        try:
            async with anyio.create_task_group() as group:

                async def stream():
                    try:
                        with anyio.move_on_after(self.total_timeout):
                            await self.stream_response(send)
                    finally:
                        group.cancel_scope.cancel()

                async def disconnect():
                    await self.listen_for_disconnect(receive)
                    group.cancel_scope.cancel()

                group.start_soon(stream)
                group.start_soon(disconnect)
        finally:
            with anyio.CancelScope(shield=True):
                await self.body_iterator.aclose()
