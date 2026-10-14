import { onScopeDispose, ref, watch } from "vue";
import { createChatClient } from "../apis/deepseek.js";
import { createStreamQueue } from "../utils/streamQueue.js";

export function useChatGeneration({
  sessionStore,
  getMessages,
  getMode,
  onError,
  onFinished,
  onRendered,
  onStart,
  onSettled,
  client = createChatClient(),
  queue = createStreamQueue(),
}) {
  const isTyping = ref(false);
  let activeGeneration = null;

  const stopGeneration = () => {
    client.abortStream();
    queue.flushNow();
    activeGeneration = null;
    isTyping.value = false;
    onFinished?.({ status: "cancelled" });
  };

  // Watch the owning array as well as the name: clearing the last conversation
  // may replace the array without changing its name.
  watch(
    () => [
      sessionStore.curname,
      sessionStore.sessionRoles[sessionStore.curname],
      sessionStore.session[sessionStore.curname],
    ],
    () => {
      if (activeGeneration) stopGeneration();
    },
    { flush: "sync" },
  );

  async function runGeneration() {
    if (isTyping.value) return;
    const message = sessionStore.sessionpush({ role: "assistant", content: "", attachments: [] });
    const generation = { message };
    activeGeneration = generation;
    isTyping.value = true;
    onStart?.();
    queue.clear();
    queue.setCallbacks((delta) => {
      if (activeGeneration !== generation) return;
      message.content += delta;
      onRendered?.();
    });
    try {
      await client.chatStream(
        getMessages(),
        (delta) => {
          if (activeGeneration === generation) queue.enqueueContent(delta);
        },
        (result) => {
          if (activeGeneration !== generation) return;
          queue.flushNow();
          isTyping.value = false;
          onFinished?.(result);
        },
        getMode(),
      );
    } catch (error) {
      if (activeGeneration === generation) {
        if (!message.content) message.content = "回复未完成，请重试。";
        onError?.(error);
      }
    } finally {
      if (activeGeneration === generation) {
        queue.flushNow();
        isTyping.value = false;
        activeGeneration = null;
        onSettled?.();
      }
    }
  }

  onScopeDispose(() => {
    stopGeneration();
    queue.destroy();
  });
  return { isTyping, stopGeneration, runGeneration };
}
