from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=32000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["thinking", "non-thinking"] = "thinking"
    messages: list[Message] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_context(self):
        if sum(len(m.content) for m in self.messages) > 64000:
            raise ValueError("Conversation exceeds 64000 characters")
        if self.messages[-1].role != "user":
            raise ValueError("The last message must be a user message")
        return self

    def upstream_payload(self, max_tokens: int) -> dict:
        payload = {
            "model": "deepseek-flash",
            "thinking": {"type": "enabled" if self.mode == "thinking" else "disabled"},
            "messages": [m.model_dump() for m in self.messages],
            "stream": True,
            "max_tokens": max_tokens,
        }
        if self.mode == "thinking":
            payload["reasoning_effort"] = "high"
        return payload
