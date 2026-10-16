import { onScopeDispose, shallowRef, watch, watchEffect } from "vue";
import { renderMarkdown } from "../utils/markdown.js";
import { highlightRevision } from "../utils/codeHighlight.js";

const FRAME_INTERVAL = 32;
const MAX_DELAY = 900;
const segmenter = new Intl.Segmenter(undefined, { granularity: "grapheme" });
const lane = (text) => ({ target: text, end: text.length, startedAt: 0, deadline: 0 });

// Presentation follows received text; request state and saved messages stay authoritative.
export function useStreamingDisplay({ messages, currentId, activeGeneration }) {
  const visible = shallowRef(null);
  const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const htmlCache = new Map();
  let job = null;
  let frame = null;
  let lastPaint = 0;
  let conversation = currentId.value;
  const stopFrame = () => {
    if (frame !== null) window.cancelAnimationFrame(frame);
    frame = null;
  };
  const reset = () => {
    stopFrame();
    job = null;
    visible.value = null;
  };
  const publish = () => {
    visible.value = {
      id: job.id,
      content: job.content.target.slice(0, job.content.end),
      reasoning: job.reasoning.target.slice(0, job.reasoning.end),
      pending:
        job.content.end < job.content.target.length ||
        job.reasoning.end < job.reasoning.target.length,
    };
  };
  const flush = (item) => {
    stopFrame();
    job.content = lane(item.content || "");
    job.reasoning = lane(item.reasoning_content || "");
    publish();
  };
  const advance = (field, timestamp, elapsed) => {
    const remaining = field.target.length - field.end;
    if (!remaining) return;
    const timeLeft = Math.max(FRAME_INTERVAL, field.deadline - timestamp);
    const count = Math.max(1, Math.ceil((remaining * elapsed) / timeLeft));
    let added = 0;
    for (const { segment } of segmenter.segment(field.target.slice(field.end))) {
      field.end += segment.length;
      added += segment.length;
      if (added >= count) break;
    }
  };
  const schedule = () => {
    if (frame !== null) return;
    const scheduledJob = job;
    frame = window.requestAnimationFrame((timestamp) => {
      if (job !== scheduledJob) return;
      frame = null;
      const elapsed = timestamp - lastPaint;
      if (elapsed >= FRAME_INTERVAL) {
        advance(job.content, timestamp, elapsed);
        advance(job.reasoning, timestamp, elapsed);
        lastPaint = timestamp;
        publish();
      }
      if (
        job.content.end < job.content.target.length ||
        job.reasoning.end < job.reasoning.target.length
      )
        schedule();
    });
  };
  const queue = (field, text, now) => {
    if (text === field.target) return;
    const caughtUp = field.end === field.target.length;
    if (caughtUp) field.startedAt = now;
    const duration = Math.min(MAX_DELAY, Math.max(50, ((text.length - field.end) / 60) * 1000));
    field.deadline = Math.min(
      field.startedAt + MAX_DELAY,
      Math.max(caughtUp ? 0 : field.deadline, now + duration),
    );
    field.target = text;
  };
  watchEffect(
    () => {
      const active = activeGeneration.value;
      const here = active?.conversationId === currentId.value;
      const id = here ? active.messageId : job?.id;
      const item = messages.value.find((message) => message.id === id);
      if (conversation !== currentId.value) {
        conversation = currentId.value;
        reset();
        htmlCache.clear();
      }
      if (
        !item ||
        item.conversation_id !== currentId.value ||
        (job && !here && item.status !== "completed")
      ) {
        reset();
        return;
      }
      if (!job || job.id !== item.id || job.requestId !== item.request_id) {
        if (!here) return;
        reset();
        job = {
          id: item.id,
          requestId: item.request_id,
          content: lane(item.content || ""),
          reasoning: lane(item.reasoning_content || ""),
        };
        publish();
      }
      const content = item.content || "";
      const reasoning = item.reasoning_content || "";
      if (
        motion.matches ||
        document.visibilityState === "hidden" ||
        active?.cancelling ||
        !["generating", "completed"].includes(item.status) ||
        !content.startsWith(job.content.target) ||
        !reasoning.startsWith(job.reasoning.target)
      ) {
        flush(item);
        return;
      }
      const now = performance.now();
      const wasPending =
        job.content.end < job.content.target.length ||
        job.reasoning.end < job.reasoning.target.length;
      queue(job.content, content, now);
      queue(job.reasoning, reasoning, now);
      if (job.content.end < content.length || job.reasoning.end < reasoning.length) {
        if (!wasPending) lastPaint = now;
        schedule();
      }
    },
    { flush: "sync" },
  );
  const flushOnPreference = () => {
    if (!job || (!motion.matches && document.visibilityState !== "hidden")) return;
    const item = messages.value.find((message) => message.id === job.id);
    if (item) flush(item);
    else reset();
  };
  motion.addEventListener("change", flushOnPreference);
  document.addEventListener("visibilitychange", flushOnPreference);
  watch(
    () => messages.value.map((item) => item.id),
    (ids) => {
      const present = new Set(ids);
      for (const id of htmlCache.keys()) if (!present.has(id)) htmlCache.delete(id);
    },
  );
  onScopeDispose(() => {
    reset();
    htmlCache.clear();
    motion.removeEventListener("change", flushOnPreference);
    document.removeEventListener("visibilitychange", flushOnPreference);
  });
  const contentFor = (item) =>
    visible.value?.id === item.id ? visible.value.content : item.content || "";
  const reasoningFor = (item) =>
    visible.value?.id === item.id ? visible.value.reasoning : item.reasoning_content || "";
  const htmlFor = (item) => {
    const text = contentFor(item);
    const revision = highlightRevision.value;
    const cached = htmlCache.get(item.id);
    if (cached?.text === text && cached.revision === revision) return cached.html;
    const html = renderMarkdown(text);
    htmlCache.set(item.id, { text, html, revision });
    return html;
  };
  return {
    contentFor,
    reasoningFor,
    htmlFor,
    isRevealing: (item) => visible.value?.id === item.id && visible.value.pending,
  };
}
