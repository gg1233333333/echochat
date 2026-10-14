import copy

import pytest

from app import legacy
from app.legacy import LegacyError, normalize_legacy_snapshot


@pytest.fixture
def snapshot():
    return {
        "session": {
            "保留标题": [
                {"role": "user", "content": "旧问题", "roleId": "general"},
                {"role": "assistant", "content": "旧回答", "roleId": "general"},
                {
                    "role": "user",
                    "content": "新问题",
                    "roleId": "developer",
                    "attachments": [
                        {
                            "name": "main.py",
                            "size": 10,
                            "type": "text/x-python",
                            "body": "print(1)",
                            "note": "",
                        }
                    ],
                },
                {"role": "assistant", "content": "新回答", "roleId": "developer"},
            ],
            "新对话": [],
        },
        "sessionRoles": {"保留标题": "developer"},
        "roleContextStart": {"保留标题": 2},
        "time": {"保留标题": 1700000000000},
        "model": "thinking",
    }


def test_snapshot_identity_ignores_json_key_order_and_preserves_latest_segment(snapshot):
    normalized = normalize_legacy_snapshot(snapshot)
    assert normalized == normalize_legacy_snapshot(dict(reversed(list(snapshot.items()))))
    assert len(normalized["conversations"]) == 1
    conversation = normalized["conversations"][0]
    messages = conversation["messages"]
    assert conversation["title"] == "保留标题"
    assert conversation["created_at"] is None
    assert conversation["updated_at"] == "2023-11-14T22:13:20+00:00"
    assert [message["seq"] for message in messages] == [1, 2, 3, 4]
    assert [message["context_segment"] for message in messages] == [
        None,
        None,
        conversation["context_segment"],
        conversation["context_segment"],
    ]
    assert messages[1]["role_id"] == "general"
    assert messages[1]["related_user_index"] is None
    assert messages[3]["related_user_index"] == 2
    assert all(message["mode"] is None and message["created_at"] is None for message in messages)
    assert messages[2]["attachments"][0]["extracted_text"] == "print(1)"


def test_missing_context_boundary_does_not_invent_historical_context(snapshot):
    del snapshot["roleContextStart"]
    conversation = normalize_legacy_snapshot(snapshot)["conversations"][0]
    assert conversation["current_role_id"] == "general"
    assert all(message["context_segment"] is None for message in conversation["messages"])
    assert all(message["related_user_index"] is None for message in conversation["messages"])


def test_existing_long_title_is_preserved():
    title = "长标题" * 100
    snapshot = {"session": {title: [{"role": "user", "content": "保留历史"}]}}
    assert normalize_legacy_snapshot(snapshot)["conversations"][0]["title"] == title


def test_new_segment_without_messages_and_empty_assistant(snapshot):
    snapshot["roleContextStart"]["保留标题"] = 4
    snapshot["session"]["保留标题"][-1]["content"] = ""
    conversation = normalize_legacy_snapshot(snapshot)["conversations"][0]
    assert all(message["context_segment"] is None for message in conversation["messages"])
    assert conversation["messages"][-1]["status"] == "interrupted"


def test_assistant_without_adjacent_user_cannot_regenerate(snapshot):
    snapshot["session"]["保留标题"].append(
        {"role": "assistant", "content": "用户消息已删除", "roleId": "developer"}
    )
    messages = normalize_legacy_snapshot(snapshot)["conversations"][0]["messages"]
    assert messages[-1]["related_user_index"] is None


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        [],
        {},
        {"session": []},
        {"session": {"x": "bad"}},
        {"session": {"x": [{"role": "system"}]}},
        {"session": {"x": [{"role": []}]}},
    ],
)
def test_invalid_snapshots_fail_explicitly(invalid):
    with pytest.raises(LegacyError):
        normalize_legacy_snapshot(invalid)


def test_invalid_boundary_role_and_size_fail(snapshot, monkeypatch):
    bad = copy.deepcopy(snapshot)
    bad["roleContextStart"]["保留标题"] = 999
    with pytest.raises(LegacyError):
        normalize_legacy_snapshot(bad)
    bad = copy.deepcopy(snapshot)
    bad["session"]["保留标题"][-1]["roleId"] = "general"
    with pytest.raises(LegacyError):
        normalize_legacy_snapshot(bad)
    monkeypatch.setattr(legacy, "MAX_IMPORT_BYTES", 2)
    with pytest.raises(LegacyError) as error:
        normalize_legacy_snapshot(snapshot)
    assert error.value.code == "IMPORT_TOO_LARGE"


def test_old_attachment_truncation_is_preserved(snapshot):
    attachment = snapshot["session"]["保留标题"][2]["attachments"][0]
    attachment.update(body="字" * 8000, note="内容已截断，仅展示前 8000 字符")
    imported = normalize_legacy_snapshot(snapshot)["conversations"][0]["messages"][2][
        "attachments"
    ][0]
    assert imported["truncated"] is True
    assert len(imported["extracted_text"]) == 8000
