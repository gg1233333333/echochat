import json

import httpx
import pytest

from app.tools import ToolError, calculate, public_address, public_url, read_public_page


def test_calculator_only_accepts_bounded_arithmetic():
    assert calculate("(0.1 + 0.2) * 10") == "3.0"
    for expression in ("__import__('os')", "2 ** 100000", "[1]", "True", "1/0"):
        with pytest.raises(ToolError):
            calculate(expression)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/",
        "http://[::1]/",
        "http://169.254.169.254/",
        "http://198.18.0.1/",
        "http://10.0.0.1/",
        "https://user:password@example.com/",
        "https://example.com:8000/",
        "http://service.internal/",
        "http://224.0.0.1/",
        "http://[ff02::1]/",
        "http://[2002:7f00:1::]/",
        "http://[2001:0:4136:e378:8000:63bf:3fff:fdd2]/",
    ],
)
def test_private_and_credential_urls_are_rejected(url):
    with pytest.raises(ToolError):
        public_url(url)


async def test_web_reader_pins_public_address_and_blocks_redirect_to_private(monkeypatch):
    async def resolve(host, port):
        return "93.184.216.34"

    monkeypatch.setattr("app.tools.public_address", resolve)
    seen = []

    def upstream(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/secret"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        with pytest.raises(ToolError):
            await read_public_page("https://example.com/", client)
    assert len(seen) == 1
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "example.com"
    assert seen[0].extensions["sni_hostname"] == "example.com"
    assert "authorization" not in seen[0].headers


async def test_web_reader_extracts_text_and_never_returns_script(monkeypatch):
    async def resolve(host, port):
        return "93.184.216.34"

    monkeypatch.setattr("app.tools.public_address", resolve)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text="<html><script>secret()</script><h1>Title</h1><p>Hello world</p></html>",
                headers={"Content-Type": "text/html"},
            )
        )
    ) as client:
        result = await read_public_page("https://example.com/", client)
    assert "Hello world" in json.dumps(result)
    assert "secret()" not in json.dumps(result)


@pytest.mark.parametrize(
    "resolved",
    [
        "127.0.0.1",
        "10.0.0.1",
        "::1",
        "169.254.169.254",
        "224.0.0.1",
        "ff02::1",
        "2002:7f00:1::",
        "2001:0:4136:e378:8000:63bf:3fff:fdd2",
    ],
)
async def test_dns_rejects_nonpublic_addresses_without_public_lookup(monkeypatch, resolved):
    import asyncio

    async def resolve(*args, **kwargs):
        return [(None, None, None, None, (resolved, 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(ToolError):
        await public_address("example.com", 443)


async def test_fake_ip_is_independently_resolved_and_still_validated(monkeypatch):
    import asyncio

    async def resolve(*args, **kwargs):
        return [(None, None, None, None, ("198.18.0.8", 443))]

    async def public_dns(host):
        assert host == "example.com"
        return ["93.184.216.34"]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr("app.tools.proxy_dns_addresses", public_dns)
    assert await public_address("example.com", 443) == "93.184.216.34"

    async def private_dns(host):
        return ["127.0.0.1"]

    monkeypatch.setattr("app.tools.proxy_dns_addresses", private_dns)
    with pytest.raises(ToolError):
        await public_address("example.com", 443)


async def test_dns_rejects_a_mixed_public_and_private_answer(monkeypatch):
    import asyncio

    async def resolve(*args, **kwargs):
        return [(None, None, None, None, (ip, 443)) for ip in ("93.184.216.34", "10.0.0.1")]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(ToolError):
        await public_address("example.com", 443)
