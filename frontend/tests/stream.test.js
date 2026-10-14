import assert from "node:assert/strict";
import { test } from "node:test";
import { createChatClient } from "../src/apis/deepseek.js";
import { SSEParser } from "../src/utils/sseParser.js";
import { createStreamQueue } from "../src/utils/streamQueue.js";

const messages = [{ role: "user", content: "hello" }];
const encoder = new TextEncoder();
const frame = (name, payload) => `event: ${name}\ndata: ${JSON.stringify(payload)}\n\n`;
const done = frame("done", { finish_reason: "stop" });

function response(text, { bytewise = false, signal, keepOpen = false } = {}) {
  let cancelled = 0;
  let streamController;
  const body = new ReadableStream({
    start(controller) {
      streamController = controller;
      const bytes = encoder.encode(text);
      if (bytewise) for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
      else controller.enqueue(bytes);
      if (!keepOpen) controller.close();
    },
    cancel() {
      cancelled++;
    },
  });
  signal?.addEventListener(
    "abort",
    () => {
      if (keepOpen) streamController.error(signal.reason);
    },
    { once: true },
  );
  return {
    value: new Response(body, { headers: { "Content-Type": "text/event-stream" } }),
    body,
    cancelled: () => cancelled,
  };
}

function abortableFetch(_, { signal }) {
  return new Promise((resolve, reject) => {
    signal.addEventListener("abort", () => reject(signal.reason), { once: true });
  });
}

test("split UTF-8 / SSE frames, exactly one completion, no credentials", async () => {
  const mock = response(": heartbeat\r\n\r\n" + frame("delta", { content: "中文😊" }) + done, {
    bytewise: true,
  });
  let captured;
  let chunks = "";
  const completions = [];
  const client = createChatClient({
    fetchImpl: async (url, init) => {
      captured = { url, init };
      return mock.value;
    },
  });
  await client.chatStream(
    messages,
    (text) => {
      chunks += text;
    },
    (value) => completions.push(value),
  );
  assert.equal(chunks, "中文😊");
  assert.equal(completions.length, 1);
  assert.equal(completions[0].status, "completed");
  assert.equal(captured.url, "/api/chat/stream");
  assert.deepEqual(JSON.parse(captured.init.body), { messages, mode: "thinking" });
  assert.equal(captured.init.headers.Authorization, undefined);
  assert.equal(mock.body.locked, false);
});

test("done terminates immediately even with trailing tokens / open connection", async () => {
  const mock = response(done + frame("delta", { content: "must not render" }), { keepOpen: true });
  let count = 0;
  const client = createChatClient({ fetchImpl: async () => mock.value });
  await client.chatStream(messages, () => count++);
  assert.equal(count, 0);
  assert.equal(mock.cancelled(), 1);
  assert.equal(mock.body.locked, false);
});

test("SSE supports CRLF split across chunks, comments and multi-line data", () => {
  const parser = new SSEParser();
  const events = [];
  for (const char of ':comment\r\nevent: delta\r\ndata: {\r\ndata: "content":"x"}\r\n\r\n') {
    events.push(...parser.feed(char));
  }
  assert.deepEqual(events, [{ event: "delta", data: '{\n"content":"x"}' }]);
  assert.throws(() => new SSEParser(10).feed("data: " + "x".repeat(20)), /大小限制/);
  assert.throws(() => new SSEParser(10).feed("data:\ndata:\ndata:\n"), /大小限制/);
});

test("upstream SSE error keeps prior tokens and completes once", async () => {
  const mock = response(
    frame("delta", { content: "partial" }) +
      frame("error", {
        code: "upstream_rate_limited",
        message: "稍后重试",
        retryable: true,
        request_id: "r1",
      }),
  );
  const client = createChatClient({ fetchImpl: async () => mock.value });
  const content = [];
  const completions = [];
  await assert.rejects(
    client.chatStream(
      messages,
      (value) => content.push(value),
      (value) => completions.push(value),
    ),
    (error) =>
      error.code === "upstream_rate_limited" && error.retryable && error.requestId === "r1",
  );
  assert.deepEqual(content, ["partial"]);
  assert.equal(completions.length, 1);
  assert.equal(completions[0].status, "error");
  assert.equal(mock.body.locked, false);
});

test("structured HTTP errors and non-JSON gateway errors are classified", async () => {
  for (const [value, code] of [
    [
      new Response(JSON.stringify({ error: { code: "invalid_request", message: "invalid" } }), {
        status: 422,
      }),
      "invalid_request",
    ],
    [new Response("<html>gateway</html>", { status: 401 }), "http_error"],
  ]) {
    const client = createChatClient({ fetchImpl: async () => value });
    await assert.rejects(client.chatStream(messages), (error) => error.code === code);
  }
});

test("malformed events and EOF without done are failures, never successful completion", async () => {
  for (const [text, code] of [
    ["event: delta\ndata: bad-json\n\n", "invalid_stream"],
    [frame("delta", { content: "partial" }), "stream_truncated"],
    [frame("delta", { content: 42 }), "invalid_stream"],
  ]) {
    const mock = response(text);
    let outcome;
    const client = createChatClient({ fetchImpl: async () => mock.value });
    await assert.rejects(
      client.chatStream(messages, undefined, (value) => {
        outcome = value;
      }),
      (error) => error.code === code,
    );
    assert.equal(outcome.status, "error");
    assert.equal(mock.body.locked, false);
  }
});

test("cancel before headers is normal completion and clears timers", async () => {
  let signal;
  const client = createChatClient({
    fetchImpl: (...args) => {
      signal = args[1].signal;
      return abortableFetch(...args);
    },
  });
  let completed = 0;
  const pending = client.chatStream(messages, undefined, () => completed++);
  client.abortStream();
  assert.equal((await pending).status, "cancelled");
  assert.ok(signal.aborted);
  assert.equal(completed, 1);
});

test("cancel during body read releases the reader", async () => {
  let mock;
  const client = createChatClient({
    fetchImpl: async (_, { signal }) => {
      mock = response(frame("delta", { content: "partial" }), { keepOpen: true, signal });
      return mock.value;
    },
  });
  let received;
  const firstToken = new Promise((resolve) => {
    received = resolve;
  });
  const pending = client.chatStream(messages, received);
  await firstToken;
  client.abortStream();
  assert.equal((await pending).status, "cancelled");
  assert.equal(mock.body.locked, false);
});

test("old request cleanup cannot clear a newer request controller", async () => {
  const calls = [];
  const client = createChatClient({
    fetchImpl: (_, { signal }) =>
      new Promise((resolve, reject) => {
        calls.push({ signal, reject });
      }),
  });
  const old = client.chatStream(messages);
  const fresh = client.chatStream(messages);
  calls[0].reject(calls[0].signal.reason);
  assert.equal((await old).status, "cancelled");
  client.abortStream();
  assert.ok(calls[1].signal.aborted);
  calls[1].reject(calls[1].signal.reason);
  assert.equal((await fresh).status, "cancelled");
});

test("idle timeout aborts while awaiting headers", async () => {
  const client = createChatClient({ fetchImpl: abortableFetch, idleTimeoutMs: 10 });
  await assert.rejects(client.chatStream(messages), (error) => error.code === "idle_timeout");
});

test("heartbeats reset idle timer but do not extend total deadline", async () => {
  let timer;
  const client = createChatClient({
    idleTimeoutMs: 30,
    totalTimeoutMs: 50,
    fetchImpl: async (_, { signal }) => {
      const body = new ReadableStream({
        start(controller) {
          timer = setInterval(() => controller.enqueue(encoder.encode(": ping\n\n")), 5);
          signal.addEventListener(
            "abort",
            () => {
              clearInterval(timer);
              controller.error(signal.reason);
            },
            { once: true },
          );
        },
        cancel() {
          clearInterval(timer);
        },
      });
      return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
    },
  });
  await assert.rejects(client.chatStream(messages), (error) => error.code === "stream_timeout");
});

test("callback failure propagates and still cleans up", async () => {
  const mock = response(frame("delta", { content: "x" }) + done, { keepOpen: true });
  const client = createChatClient({ fetchImpl: async () => mock.value });
  let completed = 0;
  await assert.rejects(
    client.chatStream(
      messages,
      () => {
        throw new Error("render failed");
      },
      () => completed++,
    ),
    /render failed/,
  );
  assert.equal(completed, 1);
  assert.equal(mock.body.locked, false);
  assert.equal(mock.cancelled(), 1);
});

test("render queue flushes final tokens synchronously and cancels old frames", () => {
  const callbacks = new Map();
  let id = 0;
  const queue = createStreamQueue({
    schedule: (fn) => {
      callbacks.set(++id, fn);
      return id;
    },
    cancel: (key) => callbacks.delete(key),
  });
  const content = [];
  queue.setCallbacks((delta) => content.push(delta));
  queue.enqueueContent("last");
  queue.enqueueContent(" token");
  assert.equal(callbacks.size, 1);
  queue.flushNow();
  assert.deepEqual(content, ["last token"]);
  assert.equal(callbacks.size, 0);
  queue.enqueueContent("stale");
  queue.clear();
  assert.equal(callbacks.size, 0);
  queue.enqueueContent("unmounted");
  queue.destroy();
  assert.equal(callbacks.size, 0);
  assert.deepEqual(content, ["last token"]);
});
