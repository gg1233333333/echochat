export class SSEParser {
  constructor(maxSize = 65536) {
    this.maxSize = maxSize;
    this.buffer = "";
    this.data = [];
    this.event = "message";
    this.size = 0;
    this.skipLF = false;
  }

  feed(text) {
    const events = [];
    for (const char of text) {
      if (this.skipLF) {
        this.skipLF = false;
        if (char === "\n") continue;
      }
      if (char === "\n" || char === "\r") {
        this.skipLF = char === "\r";
        const line = this.buffer;
        this.buffer = "";
        if (!line) {
          if (this.data.length) events.push({ event: this.event, data: this.data.join("\n") });
          this.data = [];
          this.event = "message";
          this.size = 0;
        } else if (!line.startsWith(":")) {
          this.size += line.length + 1;
          const colon = line.indexOf(":");
          const field = colon < 0 ? line : line.slice(0, colon);
          let value = colon < 0 ? "" : line.slice(colon + 1);
          if (value.startsWith(" ")) value = value.slice(1);
          if (field === "data") {
            this.data.push(value);
          }
          if (field === "event") this.event = value;
        }
      } else {
        this.buffer += char;
      }
      if (this.buffer.length + this.size > this.maxSize) {
        const error = new Error("SSE 事件超过大小限制。");
        error.code = "invalid_stream";
        throw error;
      }
    }
    return events;
  }
}
