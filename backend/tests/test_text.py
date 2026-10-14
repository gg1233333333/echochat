from app.text import plain_preview


def test_preview_removes_markdown_before_truncating():
    assert plain_preview("**ChatGPT** 与 `FastAPI`", 10) == "ChatGPT 与 …"
    assert plain_preview("# 标题\n\n[说明](https://example.com)\n\n```python\nprint(1)\n```") == (
        "标题 说明 print(1)"
    )
