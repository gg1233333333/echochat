import { SSEParser } from "../utils/sseParser.js";

export class ChatStreamError extends Error {
  constructor(code, message, { retryable = false, requestId, status } = {}) {
    super(message);
    this.name = "ChatStreamError";
    this.code = code;
    this.retryable = retryable;
    this.requestId = requestId;
    this.status = status;
  }
}

// One client per chat view. An older request's finally cannot clear a newer request.
export function createChatClient({
  url = "/api/chat/stream",
  fetchImpl = (...args) => globalThis.fetch(...args),
  idleTimeoutMs = 75000,
  totalTimeoutMs = 315000,
} = {}) {
  let active = null;
  const abortStream = () => active?.controller.abort();

  async function chatStream(messages, onChunk, onDone, mode = "thinking") {
    abortStream();
    const operation = { controller: new AbortController() };
    active = operation;
    const { controller } = operation;
    let reader;
    let idleTimer;
    let totalTimer;
    let outcome = { status: "error" };
    const timeout = (code, message) =>
      controller.abort(new ChatStreamError(code, message, { retryable: true }));
    const resetIdle = () => {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(
        () => timeout("idle_timeout", "等待回复超时，请重试。"),
        idleTimeoutMs,
      );
    };
    try {
      resetIdle();
      totalTimer = setTimeout(
        () => timeout("stream_timeout", "回复超过最大生成时限，请重试。"),
        totalTimeoutMs,
      );
      const response = await fetchImpl(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ messages, mode }),
        signal: controller.signal,
      });
      if (!response.ok) {
        let payload;
        try {
          payload = await response.json();
        } catch {
          /* gateway may return HTML */
        }
        const error = payload?.error;
        throw new ChatStreamError(
          error?.code || "http_error",
          error?.message ||
            (response.status === 401 ? "请先通过站点身份验证。" : "对话服务请求失败。"),
          {
            status: response.status,
            retryable: error?.retryable ?? response.status >= 500,
            requestId: error?.request_id || response.headers.get("x-request-id"),
          },
        );
      }
      if (
        !response.body ||
        !response.headers.get("content-type")?.startsWith("text/event-stream")
      ) {
        throw new ChatStreamError("invalid_stream", "对话服务未返回事件流。");
      }
      reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8", { fatal: true });
      const decode = (bytes, stream = false) => {
        try {
          return decoder.decode(bytes, { stream });
        } catch {
          throw new ChatStreamError("invalid_stream", "对话服务返回了无效的文本编码。");
        }
      };
      const parser = new SSEParser();
      while (true) {
        const { value, done } = await reader.read();
        if (controller.signal.aborted) throw controller.signal.reason;
        if (done) {
          decode();
          throw new ChatStreamError("stream_truncated", "回复意外中断，可重新生成。", {
            retryable: true,
          });
        }
        resetIdle();
        const events = parser.feed(decode(value, true));
        for (const item of events) {
          let payload;
          try {
            payload = JSON.parse(item.data);
          } catch {
            throw new ChatStreamError("invalid_stream", "对话服务返回了无效的流事件。");
          }
          if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
            throw new ChatStreamError("invalid_stream", "对话服务返回了无效的流事件。");
          }
          if (item.event === "error") {
            throw new ChatStreamError(
              payload.code || "server_error",
              payload.message || "回复生成失败。",
              { retryable: payload.retryable, requestId: payload.request_id },
            );
          }
          if (item.event === "done") {
            outcome = { status: "completed", finishReason: payload.finish_reason };
            return outcome;
          }
          if (item.event !== "delta" || typeof payload.content !== "string") {
            throw new ChatStreamError("invalid_stream", "对话服务返回了未知的流事件。");
          }
          if (payload.content) onChunk?.(payload.content);
        }
      }
    } catch (caught) {
      let error = caught;
      if (controller.signal.aborted) {
        if (!(controller.signal.reason instanceof ChatStreamError)) {
          outcome = { status: "cancelled" };
          return outcome;
        }
        error = controller.signal.reason;
      } else if (!(error instanceof ChatStreamError) && error instanceof TypeError) {
        error = new ChatStreamError("network_error", "网络连接失败，请检查网络后重试。", {
          retryable: true,
        });
      }
      outcome = { status: "error", error };
      throw error;
    } finally {
      clearTimeout(idleTimer);
      clearTimeout(totalTimer);
      controller.abort();
      if (reader) {
        try {
          await reader.cancel();
        } catch {
          /* aborted or already closed */
        }
        reader.releaseLock();
      }
      if (active === operation) active = null;
      onDone?.(outcome);
    }
  }
  return { chatStream, abortStream };
}
