import test from "node:test";
import assert from "node:assert/strict";
import { createPinia, setActivePinia } from "pinia";
import { useSessionStore } from "../src/stores/session.js";
import { computed } from "vue";

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

async function fixture(t, rejection, { selectInitial = true } = {}) {
  const preferences = new Map();
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: { getItem: (key) => preferences.get(key) ?? null, setItem: (key, value) => preferences.set(key, value) } });
  setActivePinia(createPinia());
  let controller, requestId, cancelled = false, heldLoad, heldCreation, sentBody;
  let saved = [];
  const conversation = (id, count = 0) => ({ id, title: id, current_role_id: "general", context_segment: "segment", message_count: count, preview: "", updated_at: "2026-10-13T00:00:00Z" });
  const user = () => ({ id: "user-1", conversation_id: "c1", seq: 1, role: "user", content: "问题", status: "completed", request_id: requestId, attachments: [] });
  const assistant = (status = "generating", content = "", reasoning_content = "") => ({ id: "answer-1", conversation_id: "c1", seq: 2, role: "assistant", content, reasoning_content, status, request_id: requestId, attachments: [] });
  t.mock.method(globalThis, "fetch", async (path, init = {}) => {
    if (path === "/api/options") return json({ roles: [{ id: "general" }], modes: [{ value: "thinking" }], attachments: {}, tools: [{ name: "calculate" }, { name: "create_file" }] });
    if (path === "/api/credentials/deepseek") return json({ configured: true });
    if (path === "/api/conversations?include_empty=true") return json({ items: [conversation("c1", saved.length), conversation("c2")] });
    if (path === "/api/conversations" && init.method === "POST") {
      const response = json(conversation(heldCreation?.id || "c2"));
      if (heldCreation) await heldCreation.promise;
      return response;
    }
    if (path.includes("/messages?limit=")) {
      const response = json({ items: path.includes("c1") ? saved : [], has_more: false });
      if (heldLoad) await heldLoad.promise;
      return response;
    }
    if (path === "/api/conversations/c1/messages") {
      if (rejection) return json({ detail: { code: "invalid_file", message: "文件损坏" } }, 400);
      sentBody = init.body;
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
  if (selectInitial) await store.selectConversation("c1");
  store.setDraftText("问题");
  const emit = (type, payload) => controller.enqueue(new TextEncoder().encode(`event: ${type}\ndata: ${JSON.stringify({ request_id: requestId, conversation_id: "c1", ...payload })}\n\n`));
  return {
    store, emit, get sentBody() { return sentBody; }, get cancelled() { return cancelled; },
    start() { saved = [user(), assistant()]; emit("started", { user_message: user(), assistant_message: assistant(), conversation: conversation("c1", 2) }); },
    finish(reasoning = "") { saved = [user(), assistant("completed", "最终回复", reasoning)]; emit("done", { message: saved[1], conversation: conversation("c1", 2) }); controller.close(); },
    disconnect() { controller.close(); },
    holdLoad() {
      heldLoad = {};
      heldLoad.promise = new Promise((resolve) => { heldLoad.release = resolve; });
      return () => { heldLoad.release(); heldLoad = null; };
    },
    holdCreation(id = "c3") {
      heldCreation = { id };
      heldCreation.promise = new Promise((resolve) => { heldCreation.release = resolve; });
      return () => { heldCreation.release(); heldCreation = null; };
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

test("tool events stay with their generation and ignore stale or stopped updates", async (t) => {
  const f = await fixture(t);
  assert.equal(f.store.agentEnabled, true);
  f.store.toggleAgent();
  assert.equal(f.store.agentEnabled, false);
  const sending = f.store.send();
  await tick(); f.start(); await tick();
  const calls = [{ id: "tool-1", label: "精确计算", status: "running" }];
  f.emit("tools", { message_id: "wrong-message", tool_calls: calls });
  await tick();
  assert.equal(f.store.messages[1].tool_calls, undefined);
  await f.store.selectConversation("c2");
  f.emit("tools", { message_id: "answer-1", tool_calls: calls });
  await tick();
  assert.equal(f.store.messages.length, 0);
  await f.store.selectConversation("c1");
  assert.deepEqual(f.store.messages[1].tool_calls, calls);
  f.finish(); await sending;
  assert.equal(f.store.messages[1].tool_calls, undefined);
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

test("uncached history blocks generation and concurrent selections wait for its result", async (t) => {
  const f = await fixture(t, false, { selectInitial: false });
  const release = f.holdLoad();
  const selecting = f.store.selectConversation("c1");
  let selectedAgain = false, loadedAgain = false;
  const reselecting = f.store.selectConversation("c1").then(() => { selectedAgain = true; });
  const reloading = f.store.loadMessages("c1").then(() => { loadedAgain = true; });
  f.store.setDraftText("等待历史的草稿");
  f.store.addFiles([new File(["attachment"], "sample.txt")]);
  const sending = f.store.send();
  void sending.catch(() => {});
  try {
    await tick();
    assert.equal(f.store.isGenerating, false);
    await assert.rejects(sending, /等待.*历史.*加载/);
    assert.equal(selectedAgain, false);
    assert.equal(loadedAgain, false);
    assert.equal(f.store.ready, true);
    assert.equal(f.store.currentDraft.text, "等待历史的草稿");
    assert.equal(f.store.currentDraft.files[0].name, "sample.txt");
  } finally {
    if (f.store.isGenerating) { f.start(); f.finish(); }
    await sending.catch(() => {});
    release();
    await Promise.all([selecting, reselecting, reloading]);
  }
  assert.equal(f.store.pages.c1.loading, false);
  const accepted = f.store.send();
  await tick(); f.start(); f.finish(); await accepted;
  assert.deepEqual(f.store.messages.map((item) => item.id), ["user-1", "answer-1"]);
  assert.equal(f.store.messages[1].status, "completed");
});

test("a delayed new conversation is saved without replacing a later selection or draft", async (t) => {
  const f = await fixture(t);
  const release = f.holdCreation();
  const creating = f.store.newConversation();
  await f.store.selectConversation("c2");
  f.store.setDraftText("后续选择的草稿");
  f.store.addFiles([new File(["attachment"], "sample.txt")]);
  release();
  const created = await creating;
  assert.equal(f.store.currentId, "c2");
  assert.equal(f.store.currentDraft.text, "后续选择的草稿");
  assert.equal(f.store.currentDraft.files[0].name, "sample.txt");
  assert.equal(f.store.conversations[created.id].id, "c3");
  await f.store.selectConversation(created.id);
  assert.deepEqual(f.store.messages, []);
  assert.equal(f.store.currentDraft.text, "");
  await f.store.selectConversation("c2");
  assert.equal(f.store.currentDraft.text, "后续选择的草稿");
});


test("individual tool permissions persist and are included in the accepted request snapshot", async (t) => {
  const f = await fixture(t);
  assert.deepEqual(f.store.allowedTools, ["calculate", "create_file"]);
  f.store.setTool("create_file", false);
  f.store.setTool("unknown", true);
  assert.deepEqual(f.store.allowedTools, ["calculate"]);
  assert.deepEqual(JSON.parse(localStorage.getItem("echochat.preferences")).selectedTools, ["calculate"]);
  const pending = f.store.send();
  await tick(); f.start(); await tick();
  assert.deepEqual(JSON.parse(f.sentBody.get("allowed_tools")), ["calculate"]);
  f.store.setTool("create_file", true);
  assert.deepEqual(JSON.parse(f.sentBody.get("allowed_tools")), ["calculate"]);
  f.finish(); await pending;
});


test("key submission keeps the target observed by the dialog", async (t) => {
  const f = await fixture(t);
  let submitted;
  t.mock.method(globalThis, "fetch", async (path, init) => {
    assert.equal(path, "/api/credentials/deepseek");
    submitted = JSON.parse(init.body);
    return json({ configured: true });
  });
  const observed = { base_url: "https://observed.example/v1", protocol: "openai" };
  await f.store.configureKey("fake-key", observed);
  assert.deepEqual(submitted, { api_key: "fake-key", target: observed });
});
