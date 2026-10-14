from dataclasses import dataclass


@dataclass
class ChatError(Exception):
    code: str
    message: str
    status: int = 502
    retryable: bool = False

    def payload(self, request_id: str) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "request_id": request_id,
        }


def provider_error(status: int) -> ChatError:
    if status in (401, 403):
        return ChatError("upstream_authentication", "模型服务凭据无效，请联系管理员。")
    if status == 402:
        return ChatError("upstream_quota_exceeded", "模型服务余额不足，请联系管理员。", 503)
    if status == 429:
        return ChatError("upstream_rate_limited", "模型服务请求过多，请稍后重试。", 429, True)
    if status >= 500:
        return ChatError("upstream_unavailable", "模型服务暂时不可用。", 503, True)
    return ChatError("upstream_invalid_request", "模型服务拒绝了请求，请缩短上下文后重试。")
