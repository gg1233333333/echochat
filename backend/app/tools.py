import ast
import asyncio
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from decimal import Decimal, DecimalException, localcontext
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urljoin, urlsplit
from uuid import UUID

import httpx
from ddgs import DDGS
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from app.database import Database
from app.models import Artifact, Attachment, Message, new_id


class ToolError(ValueError):
    pass


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Calculate(Arguments):
    expression: str = Field(min_length=1, max_length=500)


class ListAttachments(Arguments):
    pass


class ReadAttachment(Arguments):
    attachment_id: str = Field(min_length=36, max_length=36)


class CreateFile(Arguments):
    name: str = Field(min_length=1, max_length=100)
    format: Literal["md", "txt", "json"]
    content: str = Field(min_length=1, max_length=80000)


class SearchWeb(Arguments):
    query: str = Field(min_length=1, max_length=300)


class ReadWebpage(Arguments):
    url: str = Field(min_length=1, max_length=2000)


TOOL_DEFINITIONS = {
    "calculate": (Calculate, "精确计算", "计算算术表达式，支持 + - * / % ** 和括号，不执行代码。"),
    "list_attachments": (
        ListAttachments,
        "查找附件",
        "列出当前对话上下文的附件 ID、名称和提取状态。",
    ),
    "read_attachment": (
        ReadAttachment,
        "读取附件",
        "按 ID 读取当前对话的已提取附件正文，返回截断和提取状态。",
    ),
    "create_file": (
        CreateFile,
        "生成文件",
        "生成可下载的 Markdown、纯文本或 JSON 文件；不写入用户文件系统。",
    ),
    "search_web": (
        SearchWeb,
        "搜索网页",
        "使用免 Key 搜索查询公开网页，返回标题、网址和摘要。可能限流或不可用。",
    ),
    "read_webpage": (
        ReadWebpage,
        "读取网页",
        "读取公开 HTTP(S) 网页文字，不执行脚本、不登录。返回来源 URL。",
    ),
}


def tool_schemas(allowed=None):
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": schema.model_json_schema(),
            },
        }
        for name, (schema, _, description) in TOOL_DEFINITIONS.items()
        if allowed is None or name in allowed
    ]


def calculate(expression: str) -> str:
    try:
        tree = ast.parse(expression, mode="eval")
        if len(list(ast.walk(tree))) > 100:
            raise ToolError("表达式过于复杂。")

        def evaluate(node):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                return Decimal(ast.get_source_segment(expression, node))
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = evaluate(node.operand)
                return -value if isinstance(node.op, ast.USub) else value
            if isinstance(node, ast.BinOp):
                left, right = evaluate(node.left), evaluate(node.right)
                if max(abs(left), abs(right)) > Decimal("1e100"):
                    raise ToolError("数值超出计算范围。")
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, ast.Div):
                    return left / right
                if isinstance(node.op, ast.Mod):
                    return left % right
                if isinstance(node.op, ast.Pow) and abs(right) <= 100:
                    return left**right
            raise ToolError("仅支持有界算术表达式。")

        with localcontext() as context:
            context.prec = 30
            result = evaluate(tree.body)
            if not result.is_finite() or abs(result) > Decimal("1e100"):
                raise ToolError("数值超出计算范围。")
            return str(result)
    except (SyntaxError, DecimalException, ValueError, RecursionError):
        raise ToolError("无法计算，请检查表达式、数值范围和除数。") from None


def public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    # is_global also includes multicast; transition IPv6 can embed a private IPv4 target.
    if not address.is_global or address.is_multicast or address.is_reserved:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        return address.sixtofour is None and address.teredo is None
    return True


def public_url(url: str):
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if (
            parts.scheme not in {"http", "https"}
            or not host
            or parts.username
            or parts.password
            or parts.port not in (None, 80, 443)
            or "%" in host
            or "\\" in url
            or any(ord(c) < 33 for c in url)
        ):
            raise ValueError()
        host = host.rstrip(".").lower()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not public_ip(host):
            raise ValueError()
        return parts
    except ValueError:
        raise ToolError("仅支持公开 HTTP(S) 网页，禁止本机和内网地址。") from None


async def proxy_dns_addresses(host: str) -> list[str]:
    async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
        response = await client.get(
            "https://1.1.1.1/dns-query",
            params={"name": host, "type": "A"},
            headers={"Accept": "application/dns-json"},
        )
        response.raise_for_status()
        try:
            return [row["data"] for row in response.json().get("Answer", []) if row["type"] == 1]
        except (ValueError, TypeError, KeyError):
            raise ToolError("公共 DNS 未返回有效地址。") from None


async def public_address(host: str, port: int) -> str:
    addresses = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips = [item[4][0] for item in addresses]
    # Clash Fake-IP uses the benchmarking range. Resolve it independently, never connect to it.
    if ips and all(ipaddress.ip_address(ip) in ipaddress.ip_network("198.18.0.0/15") for ip in ips):
        ips = await proxy_dns_addresses(host)
    if not ips or any(not public_ip(ip) for ip in ips):
        raise ToolError("网页地址指向本机、内网或保留地址，已拒绝读取。")
    return ips[0]


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template", "svg"}:
            self.hidden += 1
        if not self.hidden and tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "template", "svg"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


async def read_public_page(url: str, client: httpx.AsyncClient) -> dict:
    for _ in range(4):
        parts = public_url(url)
        host = parts.hostname.encode("idna").decode("ascii")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        address = await public_address(host, port)
        # Pin the validated address while retaining TLS hostname verification; redirects revalidate.
        pinned = httpx.URL(url).copy_with(host=address)
        async with client.stream(
            "GET",
            pinned,
            headers={
                "Host": httpx.URL(url).netloc.decode(),
                "User-Agent": "EchoChat/0.1",
                "Accept": "text/html,text/plain",
                "Connection": "close",
            },
            extensions={"sni_hostname": host},
            follow_redirects=False,
            timeout=12,
        ) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers.get("location", ""))
                continue
            if response.is_error:
                raise ToolError(f"网页返回 HTTP {response.status_code}，无法读取。")
            mime = response.headers.get("content-type", "").lower()
            if not any(value in mime for value in ("text/html", "text/plain", "application/json")):
                raise ToolError("该地址不是可读取的文字网页。")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 1024 * 1024:
                    raise ToolError("网页超过 1 MiB 读取限制。")
            text = bytes(content).decode(response.encoding or "utf-8", errors="replace")
            if "html" in mime:
                parser = PageText()
                parser.feed(text)
                text = " ".join(parser.parts)
            text = re.sub(r"[ \t]+", " ", text).strip()
            if not text:
                raise ToolError("网页未返回可提取文字，可能需要登录或执行脚本。")
            return {"url": url, "text": text[:12000], "truncated": len(text) > 12000}
    raise ToolError("网页重定向次数超过限制。")


def search_web(query: str) -> dict:
    # Use only the named public search backend; do not enable distributed search or telemetry.
    rows = DDGS(timeout=10).text(query, backend="duckduckgo", max_results=5)
    results = []
    for row in rows:
        url = row.get("href", "")
        try:
            public_url(url)
        except ToolError:
            continue
        results.append(
            {
                "title": str(row.get("title", ""))[:300],
                "url": url[:2000],
                "snippet": str(row.get("body", ""))[:1000],
            }
        )
    if not results:
        raise ToolError("搜索未返回可用结果，请更换关键词或稍后重试。")
    return {"results": results}


@dataclass
class ToolRuntime:
    db: Database
    client: httpx.AsyncClient
    conversation_id: str
    message_id: str
    segment: str
    through_seq: int
    allowed_tools: frozenset[str] | None = None
    operation_id: str | None = None

    def attachments_query(self):
        return (
            select(Attachment)
            .join(Message)
            .where(
                Message.conversation_id == self.conversation_id,
                Message.context_segment == self.segment,
                Message.seq < self.through_seq,
            )
        )

    async def execute(self, name: str, arguments: str) -> dict:
        if self.allowed_tools is not None and name not in self.allowed_tools:
            raise ToolError("此工具未获本次运行授权，已拒绝执行。")
        if name not in TOOL_DEFINITIONS:
            raise ToolError("不支持的工具。")
        try:
            args = TOOL_DEFINITIONS[name][0].model_validate_json(arguments)
        except ValidationError:
            raise ToolError("工具参数不符合格式，请根据工具定义修正。") from None
        if isinstance(args, Calculate):
            return {"result": calculate(args.expression)}
        if isinstance(args, ListAttachments):
            async with self.db.sessions() as session:
                rows = (await session.scalars(self.attachments_query().limit(40))).all()
            return {
                "attachments": [
                    {"id": a.id, "name": a.name, "status": a.status, "truncated": a.truncated}
                    for a in rows
                ]
            }
        if isinstance(args, ReadAttachment):
            try:
                UUID(args.attachment_id)
            except ValueError:
                raise ToolError("附件 ID 无效。") from None
            async with self.db.sessions() as session:
                item = await session.scalar(
                    self.attachments_query().where(Attachment.id == args.attachment_id)
                )
                if item is None:
                    raise ToolError("当前对话上下文中找不到该附件。")
                return {
                    "name": item.name,
                    "text": item.extracted_text,
                    "status": item.status,
                    "note": item.note,
                    "truncated": item.truncated,
                }
        if isinstance(args, CreateFile):
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", args.name).strip(" .")
            if not name:
                raise ToolError("文件名无效。")
            if args.format == "json":
                try:
                    json.loads(args.content)
                except ValueError:
                    raise ToolError("生成的 JSON 文件内容格式不正确。") from None
            if not name.lower().endswith(f".{args.format}"):
                name += f".{args.format}"
            mime = {"md": "text/markdown", "txt": "text/plain", "json": "application/json"}[
                args.format
            ]
            artifact_id = new_id()
            async with self.db.sessions.begin() as session:
                await session.execute(
                    insert(Artifact)
                    .values(
                        id=artifact_id,
                        message_id=self.message_id,
                        name=name,
                        mime=mime,
                        content=args.content,
                        operation_id=self.operation_id,
                    )
                    .on_conflict_do_nothing(index_elements=["operation_id"])
                )
                row = (
                    await session.execute(
                        select(
                            Artifact.id,
                            Artifact.name,
                            Artifact.content,
                            Artifact.message_id,
                        ).where(
                            Artifact.operation_id == self.operation_id
                            if self.operation_id
                            else Artifact.id == artifact_id
                        )
                    )
                ).one()
                if (row.name, row.content, row.message_id) != (name, args.content, self.message_id):
                    raise ToolError("同一工具操作标识的文件参数不一致，已拒绝重复创建。")
                artifact_id = row.id
            return {
                "artifact_id": artifact_id,
                "name": name,
                "download_url": f"/api/artifacts/{artifact_id}/download",
            }
        if isinstance(args, SearchWeb):
            return await asyncio.to_thread(search_web, args.query)
        if isinstance(args, ReadWebpage):
            async with httpx.AsyncClient(trust_env=False) as web_client:
                return await read_public_page(args.url, web_client)
        raise ToolError("不支持的工具。")
