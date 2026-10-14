import test from "node:test";
import assert from "node:assert/strict";
import { readEvents } from "../src/apis/backend.js";

test("SSE preserves UTF-8, CRLF and multiline data across arbitrary chunks", async () => {
  const bytes = new TextEncoder().encode(': heartbeat\r\nevent: delta\r\ndata: {"content":\r\ndata: "你好"}\r\n\r\nevent: done\ndata:{"ok":true}\n\n');
  const source = new ReadableStream({ start(controller) {
    for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
    controller.close();
  } });
  const events = [];
  await readEvents(source, (type, data) => events.push([type, data]));
  assert.deepEqual(events, [["delta", { content: "你好" }], ["done", { ok: true }]]);
});

test("SSE malformed payload is an explicit failure", async () => {
  const source = new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode("event: delta\ndata: invalid\n\n"));
    controller.close();
  } });
  await assert.rejects(readEvents(source, () => {}), SyntaxError);
});
