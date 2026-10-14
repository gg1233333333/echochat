// Own the animation frame; flush the final tokens before clearing generation state.
export function createStreamQueue({
  schedule = (fn) => requestAnimationFrame(fn),
  cancel = (id) => cancelAnimationFrame(id),
} = {}) {
  let chunks = [];
  let frame = null;
  let callback = null;
  const flushNow = () => {
    if (frame !== null) cancel(frame);
    frame = null;
    const content = chunks.join("");
    chunks = [];
    if (content) callback?.(content);
  };
  const clear = () => {
    if (frame !== null) cancel(frame);
    frame = null;
    chunks = [];
  };
  return {
    setCallbacks(fn) {
      callback = fn;
    },
    enqueueContent(delta) {
      if (!delta) return;
      chunks.push(delta);
      if (frame === null)
        frame = schedule(() => {
          frame = null;
          flushNow();
        });
    },
    flushNow,
    clear,
    destroy() {
      clear();
      callback = null;
    },
  };
}
