export class ApiError extends Error {
  constructor(message, code, status) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

async function checkResponse(response) {
  if (response.ok) return response;
  const body = await response.json().catch(() => null);
  const detail = body?.detail;
  const message = Array.isArray(detail)
    ? detail.map((item) => item.msg).join("；")
    : detail?.message || (typeof detail === "string" ? detail : "请求失败，请稍后重试");
  throw new ApiError(message, detail?.code, response.status);
}

export async function api(path, { method = "GET", body, signal } = {}) {
  const response = await checkResponse(await fetch(`/api${path}`, {
    method, signal,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }));
  return response.status === 204 ? undefined : response.json();
}

// SSE records may cross any byte boundary, including a UTF-8 character or CRLF pair.
export async function readEvents(body, onEvent) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let event = "message";
  let data = [];
  const line = async (value) => {
    if (!value) {
      if (data.length) await onEvent(event, JSON.parse(data.join("\n")));
      event = "message"; data = [];
    } else if (!value.startsWith(":")) {
      const colon = value.indexOf(":");
      const field = colon < 0 ? value : value.slice(0, colon);
      let content = colon < 0 ? "" : value.slice(colon + 1);
      if (content.startsWith(" ")) content = content.slice(1);
      if (field === "event") event = content;
      if (field === "data") data.push(content);
    }
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let newline;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        await line(buffer.slice(0, newline).replace(/\r$/, ""));
        buffer = buffer.slice(newline + 1);
      }
      if (done) break;
    }
    if (buffer) await line(buffer.replace(/\r$/, ""));
    await line("");
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export async function stream(path, body, signal, onEvent) {
  const multipart = body instanceof FormData;
  const response = await checkResponse(await fetch(`/api${path}`, {
    method: "POST", signal,
    headers: multipart ? undefined : { "Content-Type": "application/json" },
    body: multipart ? body : JSON.stringify(body),
  }));
  if (!response.body) throw new Error("浏览器无法读取流式响应");
  await readEvents(response.body, onEvent);
}
