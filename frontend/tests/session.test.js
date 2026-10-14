import test from "node:test";
import assert from "node:assert/strict";
import { createPinia, setActivePinia } from "pinia";
import { useSessionStore } from "../src/stores/session.js";
import { computed } from "vue";

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

async function fixture(t, rejection) {
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: { getItem: () => null, setItem: () => {} } });
  setActivePinia(createPinia());
  let controller, requestId, cancelled = false, heldLoad;
  let saved = [];
  const conversation = (id, count = 0) => ({ id, title: id, current_role_id: "general", context_segment: "segment", message_count: count, preview: "", updated_at: "2026-10-13T00:00:00Z" });
  const user = () => ({ id: "user-1", conversation_id: "c1", seq: 1, role: "user", content: "问题", status: "completed", request_id: requestId, attachments: [] });
  const assistant = (status = "generating", content = "", reasoning_content = "") => ({ id: "answer-1", conversation_id: "c1", seq: 2, role: "assistant", content, reasoning_content, status, request_id: requestId, attachments: [] });
  t.mock.method(globalThis, "fetch", async (path, init = {}) => {
    if (path === "/api/options") return json({ roles: [{ id: "general" }], modes: [{ value: "thinking" }], attachments: {} });
    if (path === "/api/credentials/deepseek") return json({ configured: true });
    if (path === "/api/conversations?include_empty=true") return json({ items: [conversation("c1", saved.length), conversation("c2")] });
    if (path === "/api/conversations" && init.method === "POST") return json(conversation("c2"));
    if (path.includes("/messages?limit=")) {
      const response = json({ items: path.includes("c1") ? saved : [], has_more: false });
      if (heldLoad) await heldLoad.promise;
      return response;
    }
    if (path === "/api/conversations/c1/messages") {
      if (rejection) return json({ detail: { code: "invalid_file", message: "文件损坏" } }, 400);
      requestId = init.body.get("request_id");
      return new Response(new ReadableStream({ start(streamController) {
        controller = streamController;
        init.signal.addEventListener("abort", () => { try { controller.error(new DOMException("Aborted", "AbortError")); } catch { /* Already closed. */ } });
      } }), { headers: { "Content-Type": "text/event-stream" } });
    }
    if (path.startsWith("/api/generations/")) {
      cancelled = true;
      saved = [user(), assistant("cancelled", "数据库中的部分回复")];
      return json({ message: saved[1] });
    }
    if (path === "/api/messages/answer-1") return json(saved[1]);
    throw new Error(`Unexpected fetch: ${path}`);
  });
  const store = useSessionStore();
  await store.initialize();
  await store.selectConversation("c1");
  store.setDraftText("问题");
  const emit = (type, payload) => controller.enqueue(new TextEncoder().encode(`event: ${type}\ndata: ${JSON.stringify({ request_id: requestId, conversation_id: "c1", ...payload })}\n\n`));
  return {
    store, emit, get cancelled() { return cancelled; },
    start() { saved = [user(), assistant()]; emit("started", { user_message: user(), assistant_message: assistant(), conversation: conversation("c1", 2) }); },
    finish(reasoning = "") { saved = [user(), assistant("completed", "最终回复", reasoning)]; emit("done", { message: saved[1], conversation: conversation("c1", 2) }); controller.close(); },
    disconnect() { controller.close(); },
    holdLoad() {
      heldLoad = {};
      heldLoad.promise = new Promise((resolve) => { heldLoad.release = resolve; });
      return () => { heldLoad.release(); heldLoad = null; };
    },
  };
}

test("a single generation keeps its conversation across switching and rejects duplicate submit", async (t) => {
  const f = await fixture(t);
  const sending = f.store.send();
  await assert.rejects(f.store.send(), /等待当前回复/);
  await tick(); f.start(); await tick();
  assert.equal(f.store.currentDraft.text, "");
  await f.store.newConversation();
  f.store.setDraftText("另一个草稿");
  f.emit("delta", { message_id: "answer-1", content: "片段" });
  await tick();
  assert.equal(f.store.messages.length, 0);
  f.finish(); await sending;
  assert.equal(f.store.currentDraft.text, "另一个草稿");
  await f.store.selectConversation("c1");
  assert.equal(f.store.messages[1].content, "最终回复");
  assert.equal(f.store.messages[1].status, "completed");
});

test("reasoning deltas stay with their message and history restores the saved reasoning", async (t) => {
  const f = await fixture(t);
  const sending = f.store.send();
  await tick(); f.start(); await tick();
  f.emit("delta", { message_id: "answer-1", reasoning_content: "先思考" });
  f.emit("delta", { message_id: "wrong-message", reasoning_content: "错误归属" });
  f.emit("delta", { message_id: "answer-1", content: "正文", reasoning_content: "再回答" });
  await tick();
  assert.equal(f.store.messages[1].content, "正文");
  assert.equal(f.store.messages[1].reasoning_content, "先思考再回答");
  await f.store.selectConversation("c2");
  f.emit("delta", { message_id: "answer-1", content: "", reasoning_content: "完成" });
  await tick();
  assert.equal(f.store.messages.length, 0);
  f.finish("先思考再回答完成"); await sending;
  await f.store.selectConversation("c1");
  assert.equal(f.store.messages[1].reasoning_content, "先思考再回答完成");
  assert.equal(f.store.messages[1].content, "最终回复");
});

test("pre-stream validation keeps unsent text and files", async (t) => {
  const f = await fixture(t, true);
  f.store.addFiles([new File(["broken"], "bad.pdf")]);
  await assert.rejects(f.store.send(), /文件损坏/);
  assert.equal(f.store.currentDraft.text, "问题");
  assert.equal(f.store.currentDraft.files[0].name, "bad.pdf");
  assert.equal(f.store.isGenerating, false);
});

test("a newly selected conversation draft stays reactive for the send button", async (t) => {
  const f = await fixture(t);
  await f.store.newConversation();
  const disabled = computed(() => !f.store.currentDraft.text.trim() && !f.store.currentDraft.files.length);
  assert.equal(disabled.value, true);
  f.store.setDraftText("新草稿");
  assert.equal(disabled.value, false);
  f.store.setDraftText("");
  assert.equal(disabled.value, true);
  f.store.addFiles([new File(["attachment"], "sample.txt")]);
  assert.equal(disabled.value, false);
});

test("stop before started waits for acceptance and reconciles authoritative cancellation", async (t) => {
  const f = await fixture(t);
  const sending = f.store.send();
  const stopping = f.store.cancelGeneration();
  await tick();
  assert.equal(f.cancelled, false);
  f.start();
  await stopping; await sending;
  assert.equal(f.store.messages[1].status, "cancelled");
  assert.equal(f.store.messages[1].content, "数据库中的部分回复");
  assert.equal(f.store.isGenerating, false);
});

test("disconnect after started finalizes an in-flight database snapshot", async (t) => {
  const f = await fixture(t);
  const sending = f.store.send();
  const rejection = assert.rejects(sending, /响应连接中断/);
  await tick(); f.start(); await tick();
  f.disconnect(); await rejection;
  assert.equal(f.cancelled, true);
  assert.equal(f.store.messages[1].status, "cancelled");
  assert.equal(f.store.isGenerating, false);
});

test("a delayed history snapshot cannot overwrite a stream that finished meanwhile", async (t) => {
  const f = await fixture(t);
  const sending = f.store.send();
  await tick(); f.start(); await tick();
  const release = f.holdLoad();
  const loading = f.store.loadMessages("c1");
  f.finish(); await sending;
  release(); await loading;
  assert.equal(f.store.messages[1].status, "completed");
  assert.equal(f.store.messages[1].content, "最终回复");
});
