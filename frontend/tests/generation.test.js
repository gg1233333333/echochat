import assert from "node:assert/strict";
import { test } from "node:test";
import { createPinia, setActivePinia } from "pinia";
import { effectScope } from "vue";
import { useSessionStore } from "../src/stores/session.js";
import { useChatGeneration } from "../src/composables/useChatGeneration.js";
import { createStreamQueue } from "../src/utils/streamQueue.js";

function setup() {
  setActivePinia(createPinia());
  const store = useSessionStore();
  const scope = effectScope();
  const calls = [];
  const errors = [];
  let frameId = 0;
  const frames = new Map();
  const queue = createStreamQueue({
    schedule: (fn) => {
      frames.set(++frameId, fn);
      return frameId;
    },
    cancel: (id) => frames.delete(id),
  });
  const client = {
    chatStream(messages, onChunk, onDone, mode) {
      return new Promise((resolve, reject) =>
        calls.push({ messages, onChunk, onDone, mode, resolve, reject }),
      );
    },
    abortStream() {
      if (calls.length) calls[calls.length - 1].aborted = true;
    },
  };
  const generation = scope.run(() =>
    useChatGeneration({
      sessionStore: store,
      client,
      queue,
      getMessages: () => store.getMessagesForModel().slice(0, -1),
      getMode: () => store.model,
      onError: (error) => errors.push(error),
    }),
  );
  return { store, scope, calls, generation, frames, errors };
}

function finish(call, result = { status: "completed" }) {
  call.onDone(result);
  call.resolve(result);
}

test("the last token is flushed into the real Pinia message before completion", async () => {
  const { store, scope, calls, generation, frames } = setup();
  store.sessionpush({ role: "user", content: "hello" });
  const pending = generation.runGeneration();
  calls[0].onChunk("last token");
  finish(calls[0]);
  await pending;
  assert.equal(store.getcurmsgs()[1].content, "last token");
  assert.equal(generation.isTyping.value, false);
  assert.equal(frames.size, 0);
  scope.stop();
});

test("switching conversations cancels and cannot redirect late tokens or callbacks", async () => {
  const { store, scope, calls, generation } = setup();
  store.sessionpush({ role: "user", content: "first" });
  const originalName = store.curname;
  const first = generation.runGeneration();
  calls[0].onChunk("partial first");
  store.newchat();
  assert.equal(calls[0].aborted, true);
  assert.equal(store.session[originalName][1].content, "partial first");
  store.sessionpush({ role: "user", content: "second" });
  const second = generation.runGeneration();
  calls[0].onChunk("stale");
  finish(calls[0], { status: "cancelled" });
  await first;
  assert.equal(generation.isTyping.value, true);
  calls[1].onChunk("second answer");
  finish(calls[1]);
  await second;
  assert.equal(store.getcurmsgs()[1].content, "second answer");
  assert.equal(store.session[originalName][1].content, "partial first");
  scope.stop();
});

test("changing roles cancels the active stream and preserves the previous partial answer", async () => {
  const { store, scope, calls, generation } = setup();
  store.sessionpush({ role: "user", content: "first" });
  const pending = generation.runGeneration();
  calls[0].onChunk("partial");
  store.setRole("developer");
  assert.ok(calls[0].aborted);
  calls[0].onChunk("stale");
  finish(calls[0], { status: "cancelled" });
  await pending;
  assert.equal(store.getcurmsgs()[1].content, "partial");
  assert.equal(generation.isTyping.value, false);
  scope.stop();
});

test("clearing all history with the same fallback name cancels without restoring deleted data", async () => {
  const { store, scope, calls, generation } = setup();
  store.sessionpush({ role: "user", content: "first" });
  const name = store.curname;
  const pending = generation.runGeneration();
  store.clear();
  assert.equal(store.curname, name);
  assert.ok(calls[0].aborted);
  calls[0].onChunk("stale");
  finish(calls[0], { status: "cancelled" });
  await pending;
  assert.deepEqual(store.getcurmsgs(), []);
  scope.stop();
});

test("stream failure preserves partial content and shows only one classified error", async () => {
  const { store, scope, calls, generation, errors } = setup();
  store.sessionpush({ role: "user", content: "first" });
  const pending = generation.runGeneration();
  calls[0].onChunk("partial");
  const error = Object.assign(new Error("timeout"), { code: "upstream_timeout" });
  calls[0].onDone({ status: "error", error });
  calls[0].reject(error);
  await pending;
  assert.equal(store.getcurmsgs()[1].content, "partial");
  assert.deepEqual(errors, [error]);
  assert.equal(generation.isTyping.value, false);
  scope.stop();
});

test("scope disposal cancels the request and removes pending render frames", async () => {
  const { store, scope, calls, generation, frames } = setup();
  store.sessionpush({ role: "user", content: "first" });
  const pending = generation.runGeneration();
  calls[0].onChunk("partial");
  scope.stop();
  assert.ok(calls[0].aborted);
  assert.equal(frames.size, 0);
  finish(calls[0], { status: "cancelled" });
  await pending;
  assert.equal(store.getcurmsgs()[1].content, "partial");
});
