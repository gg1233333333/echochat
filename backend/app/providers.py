"""OpenAI Chat Completions SSE transport with explicit DeepSeek extensions."""

import ipaddress
import json
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

import httpx

from app.errors import AppError
from app.options import MODES
from app.tools import ToolError, public_address


@dataclass(frozen=True)
class ProviderSettings:
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-flash"
    protocol: str = "deepseek"

    def __post_init__(self):
        try:
            parts = urlsplit(self.base_url)
            host = parts.hostname or ""
            local = host in {"localhost", "127.0.0.1", "::1"}
            if not local:
                try:
                    address = ipaddress.ip_address(host)
                except ValueError:
                    address = None
                if address is not None:
                    from app.tools import public_ip

                    if not public_ip(host):
                        raise ValueError()
            if (
                not host
                or parts.username is not None
                or parts.password is not None
                or parts.query
                or parts.fragment
                or "\\" in self.base_url
                or "%" in host
                or any(ord(c) < 33 for c in self.base_url)
                or parts.scheme not in ({"http", "https"} if local else {"https"})
                or (parts.port is not None and not 1 <= parts.port <= 65535)
                or self.protocol not in {"deepseek", "openai"}
                or not self.model.strip()
                or len(self.model) > 150
                or any(ord(c) < 32 for c in self.model)
                or len(self.base_url) > 2000
            ):
                raise ValueError()
        except ValueError:
            raise AppError(
                422,
                "PROVIDER_CONFIG",
                "服务地址或模型配置无效；仅允许公网 HTTPS 或明确的本机地址。",
            ) from None

    def data(self):
        return asdict(self)


def upstream_error(response):
    mapping = {
        401: ("INVALID_API_KEY", "API Key 无效，请重新配置。"),
        403: ("UPSTREAM_FORBIDDEN", "模型服务拒绝此密钥或模型的访问权限。"),
        402: ("INSUFFICIENT_BALANCE", "模型账户余额不足。"),
        429: ("UPSTREAM_RATE_LIMIT", "模型服务请求过于频繁，请稍后重试。"),
        503: ("UPSTREAM_UNAVAILABLE", "模型服务暂不可用，请稍后重试。"),
    }
    if response.status_code == 400:
        try:
            error = response.json().get("error", {})
            description = str(error.get("code", "")) + str(error.get("message", ""))
            if "context" in description.lower() or "token" in description.lower():
                return AppError(400, "CONTEXT_TOO_LONG", "当前上下文超过模型限制，请开启新对话。")
        except (ValueError, AttributeError):
            pass
    code, message = mapping.get(response.status_code, ("UPSTREAM_REJECTED", "模型服务拒绝了请求。"))
    return AppError(502, code, message)


class ChatCompletionsProvider:
    def __init__(self, client, settings: ProviderSettings):
        self.client, self.settings = client, settings

    async def target(self, endpoint):
        url = httpx.URL(self.settings.base_url.rstrip("/") + endpoint)
        host = url.host
        # The built-in fixed HTTPS endpoint retains ordinary verified DNS/TLS behavior.
        if self.settings.base_url == ProviderSettings().base_url:
            return url, {}, {}
        if host in {"localhost", "127.0.0.1", "::1"}:
            address = "127.0.0.1" if host == "localhost" else host
        else:
            try:
                address = await public_address(host, url.port or 443)
            except (ToolError, OSError, ValueError):
                raise AppError(
                    422, "PROVIDER_ADDRESS", "服务地址未解析为允许的公网地址。"
                ) from None
        # Pinning changes the pool origin to an IP. Never reuse a TLS connection
        # authenticated for one logical host when another resolves to the same IP.
        return (
            url.copy_with(host=address),
            {"Host": url.netloc.decode(), "Connection": "close"},
            {"sni_hostname": host},
        )

    async def choices(self, messages, mode, tools, api_key):
        payload = {"model": self.settings.model, "messages": messages, "stream": True}
        if self.settings.protocol == "deepseek":
            payload.update(MODES[mode]["request"])
        else:
            payload["messages"] = [
                {k: v for k, v in message.items() if k != "reasoning_content"}
                for message in messages
            ]
        if tools:
            payload.update(tools=tools, tool_choice="auto")
        url, headers, extensions = await self.target("/chat/completions")
        headers.update(Authorization=f"Bearer {api_key}", **{"Content-Type": "application/json"})
        async with self.client.stream(
            "POST",
            url,
            json=payload,
            headers=headers,
            extensions=extensions,
            follow_redirects=False,
        ) as response:
            if response.is_redirect:
                raise AppError(
                    502, "PROVIDER_REDIRECT", "模型服务重定向已拒绝，避免向其他地址发送密钥。"
                )
            if response.is_error:
                await response.aread()
                raise upstream_error(response)
            lines = []
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    lines.append(line[5:].lstrip())
                    continue
                if line or not lines:
                    continue
                data, lines = "\n".join(lines), []
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                    if "error" in chunk:
                        raise AppError(502, "UPSTREAM_ERROR", "模型服务在生成期间返回错误。")
                    for choice in chunk.get("choices") or []:
                        if not isinstance(choice, dict):
                            raise ValueError()
                        yield choice
                        break
                except (ValueError, TypeError, AttributeError):
                    raise AppError(
                        502, "INVALID_UPSTREAM_STREAM", "模型返回了无效的数据流。"
                    ) from None

    async def test_connection(self, api_key):
        if not api_key:
            raise AppError(400, "API_KEY_REQUIRED", "请先配置当前服务的 API Key。")
        url, headers, extensions = await self.target("/models")
        headers["Authorization"] = f"Bearer {api_key}"
        try:
            async with self.client.stream(
                "GET",
                url,
                headers=headers,
                extensions=extensions,
                follow_redirects=False,
                timeout=15,
            ) as response:
                if response.is_redirect:
                    raise AppError(
                        502, "PROVIDER_REDIRECT", "连接测试拒绝重定向，未向新地址发送密钥。"
                    )
                if response.is_error:
                    await response.aread()
                    raise upstream_error(response)
        except httpx.TimeoutException:
            raise AppError(502, "UPSTREAM_TIMEOUT", "连接测试超时。") from None
        except httpx.HTTPError:
            raise AppError(502, "UPSTREAM_NETWORK", "无法连接模型服务。") from None
        return {
            "ok": True,
            "message": "GET /models 连通，未生成回复；尚未验证指定模型或工具兼容性。",
        }
