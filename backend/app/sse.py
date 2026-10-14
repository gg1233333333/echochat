import json

from .errors import ChatError


def event(name: str, payload: dict) -> bytes:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


class SSEDecoder:
    """Bounded, incremental SSE decoder supporting LF, CRLF, CR and multi-line data."""

    def __init__(self, max_size: int = 65536):
        self.buffer = ""
        self.data: list[str] = []
        self.size = 0
        self.skip_lf = False
        self.max_size = max_size

    def feed(self, text: str) -> list[str]:
        events = []
        for char in text:
            if self.skip_lf:
                self.skip_lf = False
                if char == "\n":
                    continue
            if char in "\r\n":
                self.skip_lf = char == "\r"
                line, self.buffer = self.buffer, ""
                if not line:
                    if self.data:
                        events.append("\n".join(self.data))
                    self.data = []
                    self.size = 0
                else:
                    self.size += len(line) + 1
                    if line.startswith("data:"):
                        value = line[5:]
                        if value.startswith(" "):
                            value = value[1:]
                        self.data.append(value)
            else:
                self.buffer += char
            if len(self.buffer) + self.size > self.max_size:
                raise ChatError("upstream_protocol", "模型服务返回了过大的流事件。")
        return events
