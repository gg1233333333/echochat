"""Normalize the former Pinia snapshot without guessing older role segments."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from app.attachments import MAX_TEXT_CHARS

MAX_IMPORT_BYTES = 24 * 1024 * 1024


class LegacyError(ValueError):
    def __init__(self, message: str, code: str = "INVALID_IMPORT") -> None:
        super().__init__(message)
        self.code = code


def _mapping(snapshot: dict, field: str) -> dict:
    value = snapshot.get(field, {})
    if not isinstance(value, dict):
        raise LegacyError(f"旧记录中的 {field} 格式不正确。")
    return value


def _text(value: object, field: str, *, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise LegacyError(f"旧记录中的 {field} 必须是文本。")
    return value


def _role(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in {"general", "developer"}:
        raise LegacyError(f"旧记录中的 {field} 角色不受支持。")
    return value


def _updated_at(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LegacyError("旧记录中的会话时间必须是毫秒时间戳。")
    if value == 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1000, UTC).isoformat()
    except (ValueError, OverflowError, OSError) as exc:
        raise LegacyError("旧记录中的会话时间无效。") from exc


def _attachments(value: object) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise LegacyError("旧记录中的附件必须是列表。")
    result = []
    for attachment in value:
        if not isinstance(attachment, dict):
            raise LegacyError("旧记录中的附件格式不正确。")
        name = _text(attachment.get("name"), "附件名称")
        if not name or len(name) > 255:
            raise LegacyError("旧记录中的附件名称为空或过长。")
        size = attachment.get("size", 0)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise LegacyError("旧记录中的附件大小无效。")
        body = _text(attachment.get("body"), "附件正文")
        note = _text(attachment.get("note"), "附件说明")
        truncated = len(body) > MAX_TEXT_CHARS or "截断" in note
        if len(body) > MAX_TEXT_CHARS:
            note = "内容已截断，仅保留前 8000 字符。"
        result.append(
            {
                "name": name,
                "size": size,
                "mime": _text(
                    attachment.get("type"), "附件类型", default="application/octet-stream"
                ),
                "extracted_text": body[:MAX_TEXT_CHARS],
                "status": "extracted" if body else "metadata_only",
                "note": note,
                "truncated": truncated,
            }
        )
    return result


def normalize_legacy_snapshot(snapshot: dict) -> dict:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("session"), dict):
        raise LegacyError("请选择从旧版导出的 session JSON 快照。")
    try:
        canonical = json.dumps(
            snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        encoded = canonical.encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise LegacyError("旧记录不是有效的 JSON 数据。") from exc
    if len(encoded) > MAX_IMPORT_BYTES:
        raise LegacyError("旧记录超过 24 MiB，请拆分后导入。", "IMPORT_TOO_LARGE")
    snapshot_hash = hashlib.sha256(encoded).hexdigest()
    roles = _mapping(snapshot, "sessionRoles")
    boundaries = _mapping(snapshot, "roleContextStart")
    times = _mapping(snapshot, "time")
    conversations = []
    for title, raw_messages in snapshot["session"].items():
        if not isinstance(title, str) or not title.strip():
            raise LegacyError("旧记录中的会话标题为空。")
        if not isinstance(raw_messages, list):
            raise LegacyError(f"会话“{title}”的消息必须是列表。")
        if not raw_messages:
            continue
        current_role = _role(roles.get(title), "当前会话") or "general"
        boundary = boundaries.get(title)
        if boundary is not None and (
            isinstance(boundary, bool)
            or not isinstance(boundary, int)
            or not 0 <= boundary <= len(raw_messages)
        ):
            raise LegacyError(f"会话“{title}”的角色上下文边界无效。")
        identity = hashlib.sha256(f"{snapshot_hash}\0{title}".encode()).hexdigest()
        segment = str(uuid5(NAMESPACE_URL, f"echochat:legacy:{identity}:current"))
        messages = []
        for index, raw in enumerate(raw_messages):
            if not isinstance(raw, dict) or raw.get("role") not in ("user", "assistant"):
                raise LegacyError(f"会话“{title}”的第 {index + 1} 条消息格式不正确。")
            role_id = _role(raw.get("roleId"), "消息")
            in_current_segment = boundary is not None and index >= boundary
            if in_current_segment and role_id is not None and role_id != current_role:
                raise LegacyError(f"会话“{title}”的消息角色与最近上下文边界不一致。")
            if in_current_segment:
                role_id = role_id or current_role
            content = _text(raw.get("content"), "消息正文")
            message_segment = segment if in_current_segment else None
            prior = messages[-1] if messages else None
            related_user_index = None
            if (
                raw["role"] == "assistant"
                and prior
                and prior["role"] == "user"
                and message_segment is not None
                and prior["context_segment"] == message_segment
            ):
                related_user_index = index - 1
            messages.append(
                {
                    "seq": index + 1,
                    "role": raw["role"],
                    "content": content,
                    "role_id": "general" if role_id else None,
                    "context_segment": message_segment,
                    "mode": None,
                    "related_user_index": related_user_index,
                    "status": "interrupted"
                    if raw["role"] == "assistant" and not content
                    else "completed",
                    "created_at": None,
                    "attachments": _attachments(raw.get("attachments")),
                }
            )
        conversations.append(
            {
                "import_identity": identity,
                "title": title,
                "current_role_id": "general",
                "context_segment": segment,
                "created_at": None,
                "updated_at": _updated_at(times.get(title)),
                "messages": messages,
            }
        )
    return {"snapshot_hash": snapshot_hash, "conversations": conversations}
