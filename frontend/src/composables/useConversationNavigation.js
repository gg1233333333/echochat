import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { markdownPlainText } from "@/utils/markdown";

const previewText = (text, limit) => {
  const plain = markdownPlainText((text || "").slice(0, 2000))
    .replace(/\s+/g, " ")
    .trim();
  return Array.from(plain).slice(0, limit).join("");
};

export function useConversationNavigation({ messages, currentId, scroller, onNavigate }) {
  const activeId = ref(null);
  const questionCache = new Map();
  const answerCache = new Map();
  let pendingTarget = null;
  let navigationRevision = 0;
  let queuedRevision = null;
  let visibleStart = 0;
  let activeQueued = false;
  let disposed = false;

  const cachedText = (cache, item, limit) => {
    const cached = cache.get(item.id);
    if (cached?.source === item.content) return cached.text;
    const text = previewText(item.content, limit);
    cache.set(item.id, { source: item.content, text });
    return text;
  };
  const entries = computed(() => {
    const answers = new Map();
    for (const item of messages.value) {
      if (
        item.role === "assistant" &&
        item.status === "completed" &&
        item.related_user_message_id
      ) {
        answers.set(item.related_user_message_id, cachedText(answerCache, item, 100));
      }
    }
    return messages.value.flatMap((item, index) => {
      if (item.role !== "user") return [];
      const label =
        cachedText(questionCache, item, 60) ||
        (item.attachments?.length ? `附件：${item.attachments[0].name}` : "这轮提问");
      return [{ id: item.id, index, label, preview: answers.get(item.id) || "" }];
    });
  });

  const cancelPending = () => {
    navigationRevision++;
    pendingTarget = null;
    queuedRevision = null;
  };
  const updateActive = () => {
    let current =
      entries.value.findLast((entry) => entry.index <= visibleStart) || entries.value[0];
    const next = entries.value.find((entry) => entry.index > visibleStart);
    const viewport = scroller.value?.$el;
    const row = next && viewport?.querySelector(`[data-message-id="${CSS.escape(next.id)}"]`);
    if (row) {
      // The preceding item's trailing space can still count as visible at the reading edge.
      const line =
        viewport.getBoundingClientRect().top +
        (parseFloat(getComputedStyle(viewport).paddingTop) || 0);
      const bounds = row.getBoundingClientRect();
      if (bounds.top <= line + 1 && bounds.bottom > line) current = next;
    }
    activeId.value = current?.id || null;
  };
  const scheduleActive = () => {
    if (activeQueued) return;
    activeQueued = true;
    void nextTick(() => {
      activeQueued = false;
      if (!disposed) updateActive();
    });
  };
  const reconcileTarget = async () => {
    const target = pendingTarget;
    if (!target || disposed || queuedRevision === target.revision) return;
    queuedRevision = target.revision;
    await nextTick();
    if (queuedRevision === target.revision) queuedRevision = null;
    if (disposed || target !== pendingTarget || target.revision !== navigationRevision) return;
    const instance = scroller.value;
    const viewport = instance?.$el;
    const entry = entries.value.find((item) => item.id === target.id);
    if (!viewport || !entry) {
      cancelPending();
      return;
    }
    if (entry.index !== target.index) {
      target.index = entry.index;
      instance.scrollToItem(entry.index);
      return;
    }
    const row = viewport.querySelector(`[data-message-id="${CSS.escape(target.id)}"]`);
    if (!row) return;
    const bounds = viewport.getBoundingClientRect();
    const padding = parseFloat(getComputedStyle(viewport).paddingTop) || 0;
    const rowBounds = row.getBoundingClientRect();
    const offset = rowBounds.top - bounds.top - padding;
    if (Math.abs(offset) > 1) viewport.scrollTop += offset;
    const positioned = row.getBoundingClientRect();
    const measured = instance.getItemSize(messages.value[entry.index], entry.index) > 0;
    if (measured && positioned.bottom > bounds.top && positioned.top < bounds.bottom) {
      pendingTarget = null;
      scheduleActive();
    }
  };

  // Scroller updates carry visible indices; item resize calls may omit them.
  const onUpdate = (_start, _end, visibleStartIndex) => {
    if (disposed) return;
    if (Number.isInteger(visibleStartIndex)) visibleStart = visibleStartIndex;
    scheduleActive();
    void reconcileTarget();
  };
  const navigate = (id) => {
    const entry = entries.value.find((item) => item.id === id);
    if (!entry || disposed || !scroller.value) return;
    onNavigate();
    cancelPending();
    pendingTarget = { id, index: entry.index, revision: navigationRevision };
    scroller.value.scrollToItem(entry.index);
    void reconcileTarget();
  };

  watch(currentId, () => {
    cancelPending();
    activeId.value = null;
    visibleStart = 0;
    questionCache.clear();
    answerCache.clear();
  });
  watch(
    () => messages.value.at(-1)?.status,
    (status) => {
      if (["cancelled", "failed", "interrupted"].includes(status)) cancelPending();
    },
  );
  watch(entries, (items) => {
    const users = new Set(items.map((item) => item.id));
    for (const id of questionCache.keys()) if (!users.has(id)) questionCache.delete(id);
    const answers = new Set(
      messages.value.filter((item) => item.role === "assistant").map((item) => item.id),
    );
    for (const id of answerCache.keys()) if (!answers.has(id)) answerCache.delete(id);
    if (activeId.value && !users.has(activeId.value)) activeId.value = null;
    if (pendingTarget && !users.has(pendingTarget.id)) cancelPending();
  });
  onBeforeUnmount(() => {
    disposed = true;
    cancelPending();
    questionCache.clear();
    answerCache.clear();
  });

  return { entries, activeId, onUpdate, navigate, cancelNavigation: cancelPending };
}
