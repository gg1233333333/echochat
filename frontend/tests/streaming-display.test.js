import test from "node:test";
import assert from "node:assert/strict";
import { effectScope, nextTick, ref, watchEffect } from "vue";
import { useStreamingDisplay } from "../src/composables/useStreamingDisplay.js";
import { configureCodeHighlight, loadCodeLanguage } from "../src/utils/codeHighlight.js";

function fixture(t) {
  let now = 0;
  let frameId = 0;
  const frames = new Map();
  const motion = new EventTarget();
  motion.matches = false;
  const document = new EventTarget();
  document.visibilityState = "visible";
  const window = {
    matchMedia: () => motion,
    requestAnimationFrame: (callback) => {
      frames.set(++frameId, callback);
      return frameId;
    },
    cancelAnimationFrame: (id) => frames.delete(id),
  };
  const originals = [];
  for (const [name, value] of Object.entries({ window, document })) {
    const previous = Object.getOwnPropertyDescriptor(globalThis, name);
    originals.push([name, previous]);
    Object.defineProperty(globalThis, name, { configurable: true, value });
  }
  t.mock.method(performance, "now", () => now);
  const messages = ref([]);
  const currentId = ref("c1");
  const activeGeneration = ref(null);
  const scope = effectScope();
  const display = scope.run(() => useStreamingDisplay({ messages, currentId, activeGeneration }));
  t.after(() => {
    scope.stop();
    for (const [name, previous] of originals) {
      if (previous) Object.defineProperty(globalThis, name, previous);
      else delete globalThis[name];
    }
  });
  const start = (id = "a1", content = "") => {
    messages.value = [
      {
        id,
        conversation_id: currentId.value,
        request_id: id,
        role: "assistant",
        status: "generating",
        content,
        reasoning_content: "",
      },
    ];
    activeGeneration.value = {
      conversationId: currentId.value,
      messageId: id,
      requestId: id,
    };
    return messages.value[0];
  };
  const step = (ms = 16) => {
    now += ms;
    const scheduled = [...frames.values()];
    frames.clear();
    scheduled.forEach((callback) => callback(now));
  };
  return {
    display,
    messages,
    currentId,
    activeGeneration,
    frames,
    scope,
    start,
    step,
    motion,
    document,
  };
}

test("a burst produces bounded intermediate grapheme prefixes without changing received text", (t) => {
  const f = fixture(t);
  const item = f.start();
  const text = "灵感🙂👩‍💻🇨🇳e\u0301".repeat(50);
  item.content = text;
  assert.equal(f.display.contentFor(item), "");
  const boundaries = new Set([""]);
  let prefix = "";
  for (const { segment } of new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(
    text,
  )) {
    prefix += segment;
    boundaries.add(prefix);
  }
  const paints = new Set();
  for (let i = 0; i < 60; i++) {
    f.step();
    const shown = f.display.contentFor(item);
    assert.ok(boundaries.has(shown));
    paints.add(shown);
    assert.equal(item.content, text);
  }
  assert.ok(paints.size > 3);
  assert.equal(f.display.contentFor(item), text);
  assert.equal(f.display.isRevealing(item), false);
  assert.equal(f.frames.size, 0);
});

test("small deltas and reasoning appear promptly; completed messages finish their pending reveal", (t) => {
  const f = fixture(t);
  const item = f.start();
  item.reasoning_content = "思考这个问题";
  item.content = "第一段回答";
  f.step(32);
  assert.ok(f.display.contentFor(item).length > 0);
  assert.ok(f.display.reasoningFor(item).length > 0);
  item.content += "后续内容".repeat(80);
  item.status = "completed";
  f.activeGeneration.value = null;
  assert.notEqual(f.display.contentFor(item), item.content);
  for (let i = 0; i < 60; i++) f.step();
  assert.equal(f.display.contentFor(item), item.content);
  assert.equal(f.display.reasoningFor(item), item.reasoning_content);
  assert.equal(f.frames.size, 0);
});

test("a short prefix followed by a large chunk gets a smooth window with a bounded delay", (t) => {
  const f = fixture(t);
  const item = f.start();
  item.content = "```python\n";
  f.step(32);
  f.step(32);
  f.step(16);
  item.content += "print('长代码块')\n".repeat(160);
  item.status = "completed";
  f.activeGeneration.value = null;
  f.step(200);
  assert.notEqual(f.display.contentFor(item), item.content);
  for (let i = 0; i < 40; i++) f.step();
  assert.equal(f.display.contentFor(item), item.content);
  assert.equal(f.frames.size, 0);
});

test("cancel, error, authoritative replacement and deletion cancel queued display work", (t) => {
  const f = fixture(t);
  for (const status of ["cancelled", "failed", "interrupted"]) {
    const item = f.start(status);
    item.content = "已收到内容".repeat(100);
    f.step(32);
    item.status = status;
    f.activeGeneration.value = null;
    assert.equal(f.display.contentFor(item), item.content);
    assert.equal(f.frames.size, 0);
  }
  const item = f.start("replace");
  item.content = "已收到内容".repeat(100);
  item.content = "服务端最终修正";
  assert.equal(f.display.contentFor(item), item.content);
  assert.equal(f.frames.size, 0);
  item.content += "后续".repeat(100);
  f.messages.value = [];
  assert.equal(f.frames.size, 0);
});

test("switching conversation discards old frames and opens received history instantly", (t) => {
  const f = fixture(t);
  const item = f.start();
  item.content = "长回答".repeat(300);
  const stale = [...f.frames.values()][0];
  f.currentId.value = "c2";
  f.messages.value = [];
  assert.equal(f.frames.size, 0);
  stale(32);
  f.currentId.value = "c1";
  f.messages.value = [item];
  assert.equal(f.display.contentFor(item), item.content);
  assert.equal(f.frames.size, 0);
  const replacement = f.start("a2");
  replacement.content = "新的回复";
  stale(64);
  assert.equal(f.display.contentFor(replacement), "");
  replacement.content += "后续";
  assert.equal(f.frames.size, 1);
});

test("hidden pages and reduced motion flush text without leaving animation loops", (t) => {
  const f = fixture(t);
  const item = f.start();
  item.content = "内容".repeat(200);
  f.document.visibilityState = "hidden";
  f.document.dispatchEvent(new Event("visibilitychange"));
  assert.equal(f.display.contentFor(item), item.content);
  assert.equal(f.frames.size, 0);
  item.content += "后台追加";
  assert.equal(f.display.contentFor(item), item.content);
  f.document.visibilityState = "visible";
  f.document.dispatchEvent(new Event("visibilitychange"));
  item.content += "继续显示".repeat(100);
  assert.equal(f.frames.size, 1);
  f.motion.matches = true;
  f.motion.dispatchEvent(new Event("change"));
  assert.equal(f.display.contentFor(item), item.content);
  assert.equal(f.frames.size, 0);
  f.motion.matches = false;
  f.motion.dispatchEvent(new Event("change"));
  item.content += "最后一段";
  assert.equal(f.frames.size, 1);
  f.scope.stop();
  assert.equal(f.frames.size, 0);
});

test("same-task start, delta and done still reveal rather than repainting a full answer", (t) => {
  const f = fixture(t);
  const item = f.start();
  item.content = "同批到达".repeat(200);
  item.status = "completed";
  f.activeGeneration.value = null;
  assert.equal(f.display.contentFor(item), "");
  f.step(32);
  assert.ok(f.display.contentFor(item).length > 0);
  assert.notEqual(f.display.contentFor(item), item.content);
});

test("unfinished code fences render safely, then close into the full highlighted answer", (t) => {
  const f = fixture(t);
  const item = f.start();
  item.content = "```js\nconst html = '<script>alert(1)</script>';\n".repeat(20);
  f.step(32);
  const first = f.display.htmlFor(item);
  assert.ok(first.includes("<pre"));
  assert.ok(!first.includes("<script>"));
  assert.equal(f.display.htmlFor(item), first);
  item.content += "\n```\n结束。";
  for (let i = 0; i < 60; i++) f.step();
  assert.ok(f.display.htmlFor(item).includes("结束。"));
  assert.ok(!f.display.htmlFor(item).includes("<script>"));
});

test("a loaded grammar refreshes cached history without changing the saved message", async (t) => {
  const f = fixture(t);
  let finishDownload;
  let downloads = 0;
  configureCodeHighlight({
    aliases: { py: "python", python: "python" },
    dependencies: { python: [] },
    loaders: {
      python: () => {
        downloads++;
        return new Promise((resolve) => {
          finishDownload = resolve;
        });
      },
    },
  });
  const content = '```py\nprint("saved")\n```';
  f.messages.value = [{ id: "history", conversation_id: "c1", status: "completed", content }];
  let html;
  f.scope.run(() =>
    watchEffect(() => {
      html = f.display.htmlFor(f.messages.value[0]);
    }),
  );
  assert.doesNotMatch(html, /hljs-built_in/);
  const python = await import("highlight.js/lib/languages/python");
  finishDownload(python);
  await loadCodeLanguage("py");
  await nextTick();
  assert.match(html, /hljs-built_in/);
  assert.equal(f.messages.value[0].content, content);
  assert.equal(downloads, 1);
  assert.equal(f.frames.size, 0);
});
