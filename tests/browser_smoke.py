"""Run against the isolated browser-test services on localhost:5174."""

import json
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.environ.get("ECHOCHAT_TEST_URL", "http://127.0.0.1:5174")
TEST_KEY = "echochat-browser-test-key"
RESULTS = Path(__file__).resolve().parents[1] / "test-results"


def run():
    RESULTS.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        launch_options = {"headless": True}
        if sys.platform == "win32":
            launch_options["channel"] = "msedge"
        browser = playwright.chromium.launch(**launch_options)
        context = browser.new_context(
            viewport={"width": 1440, "height": 960},
            permissions=["clipboard-read", "clipboard-write"],
        )
        context.add_init_script("""
            localStorage.setItem('echochat.opening.v1', 'seen');
            window.SpeechRecognition = class {
                constructor() { window.testRecognition = this; }
                start() {}
                stop() { this.onend?.(); }
                abort() { this.onend?.(); }
            };
        """)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def api(method, path, data=None):
            response = context.request.fetch(BASE_URL + "/api" + path, method=method, data=data)
            assert response.ok, f"{method} {path}: {response.status} {response.text()}"
            return response.json() if response.status != 204 else None

        def conversations():
            return api("GET", "/conversations")["items"]

        def messages(conversation_id):
            return api("GET", f"/conversations/{conversation_id}/messages")["items"]

        def wait_finished():
            expect(page.get_by_role("button", name="发送", exact=True)).to_be_visible(timeout=20000)

        def send(text):
            page.locator("textarea.inputbox").fill(text)
            page.get_by_role("button", name="发送", exact=True).click()
            wait_finished()

        def select_conversation(title):
            page.locator(".conversation-item").filter(
                has=page.locator(".conversation-item__title", has_text=title)
            ).first.click()

        def settings_command(name):
            page.get_by_role("button", name="设置", exact=True).click()
            page.get_by_role("menuitem", name=re.compile(name)).click()

        # Refuse to run against the real backend or delete the user's history.
        fixture = context.request.get(BASE_URL + "/api/test/requests")
        assert fixture.ok, "Start tests/browser_server.py before running this test."
        calls_before = len(fixture.json()["items"])
        api("DELETE", "/conversations")
        api("DELETE", "/credentials/deepseek")
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")
        expect(page.locator("textarea.inputbox")).to_be_visible()

        # Credential is configured in the page and never persisted in browser storage.
        settings_command("API Key 设置")
        page.get_by_placeholder("输入 DeepSeek API Key").fill(TEST_KEY)
        page.get_by_role("button", name="使用密钥", exact=True).click()
        expect(page.get_by_placeholder("输入 DeepSeek API Key")).to_have_value("")
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).not_to_be_visible()
        assert api("GET", "/credentials/deepseek") == {"configured": True}
        assert TEST_KEY not in page.evaluate("JSON.stringify(localStorage)")

        page.get_by_role("button", name="语音输入", exact=True).click()
        expect(page.get_by_role("button", name="取消语音启动", exact=True)).to_be_visible()
        expect(page.locator(".speech-preview")).to_contain_text("正在启动语音")
        page.get_by_role("button", name="取消语音启动", exact=True).click()
        expect(page.get_by_role("button", name="语音输入", exact=True)).to_be_visible()
        page.get_by_role("button", name="语音输入", exact=True).click()
        page.evaluate("testRecognition.onerror({error:'not-allowed'})")
        expect(page.locator(".composer-feedback")).to_contain_text("权限未获允许")
        page.get_by_role("button", name="关闭语音提示", exact=True).click()
        page.get_by_role("button", name="语音输入", exact=True).click()
        page.evaluate("""() => {
            testRecognition.onstart();
            const first = [{transcript: '你好'}]; first.isFinal = true;
            const second = [{transcript: '世界'}]; second.isFinal = true;
            testRecognition.onresult({resultIndex: 0, results: [first]});
            testRecognition.onresult({resultIndex: 1, results: [first, second]});
        }""")
        expect(page.locator("textarea.inputbox")).to_have_value("你好 世界")
        page.get_by_role("button", name="停止语音", exact=True).click()
        page.locator("textarea.inputbox").dispatch_event(
            "keydown", {"key": "Enter", "isComposing": True, "keyCode": 229}
        )
        expect(page.locator("textarea.inputbox")).to_have_value("你好 世界")
        assert len(api("GET", "/test/requests")["items"]) == calls_before

        send("第一条测试消息")
        first = conversations()[0]
        first_id = first["id"]
        assert len(messages(first_id)) == 2
        expect(page.locator(".assistant-message .message-body")).to_contain_text("模拟回答")
        saved_reasoning = messages(first_id)[-1]["reasoning_content"]
        assert saved_reasoning.startswith("先理解问题。")
        reasoning_toggle = page.get_by_role("button", name="思考过程", exact=True)
        expect(reasoning_toggle).to_have_attribute("aria-expanded", "false")
        expect(page.locator(".reasoning-content")).to_have_count(0)
        reasoning_toggle.click()
        expect(page.locator(".reasoning-content")).to_have_text(saved_reasoning)
        assert page.locator(".reasoning-content img").count() == 0
        reasoning_toggle.click()
        expect(page.locator(".reasoning-content")).to_have_count(0)
        assert page.locator(".assistant-message .message-body img").count() == 0
        assert not page.evaluate("window.__unsafeHtmlExecuted || false")
        page.locator(".assistant-message").get_by_role(
            "button", name="复制纯文本", exact=True
        ).click()
        plain = page.evaluate("navigator.clipboard.readText()")
        assert "**" not in plain and "```" not in plain and "\n" in plain
        assert "复制" not in plain and "print('echochat')" in plain
        page.locator(".assistant-message").get_by_role(
            "button", name="更多消息操作", exact=True
        ).click()
        page.get_by_role("menuitem", name="复制 Markdown", exact=True).click()
        assert "**模拟回答**" in page.evaluate("navigator.clipboard.readText()")
        page.locator(".assistant-message .copy-btn").click()
        assert page.evaluate("navigator.clipboard.readText()").strip() == "print('echochat')"
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page.locator(".assistant-message .message-body")).to_contain_text("模拟回答")
        expect(reasoning_toggle).to_have_attribute("aria-expanded", "false")
        reasoning_toggle.click()
        expect(page.locator(".reasoning-content")).to_have_text(saved_reasoning)
        reasoning_toggle.click()
        assert api("GET", "/credentials/deepseek")["configured"]
        title_button = page.get_by_role("button", name="重命名对话", exact=True)
        title_button.click()
        title_input = page.locator(".title-input input")
        title_input.fill("取消的标题")
        title_input.press("Escape")
        expect(title_button).to_have_text(first["title"])
        expect(title_button).to_be_focused()
        title_button.click()
        title_input.fill("手动保存的标题")
        title_input.press("Enter")
        expect(title_button).to_have_text("手动保存的标题")
        expect(title_button).to_be_focused()
        title_button.click()
        title_input.fill("失焦保存的标题")
        page.locator("textarea.inputbox").click()
        expect(title_button).to_have_text("失焦保存的标题")
        expect(page.locator("textarea.inputbox")).to_be_focused()
        page.locator(".model-select").click()
        page.get_by_role("option", name=re.compile("快速回答")).click()

        # MIME is deliberately octet-stream: .vue extension must still extract text.
        attachment_text = "const source = 1;\n" * 600
        page.locator('input[type="file"][multiple]').set_input_files(
            {
                "name": "component.vue",
                "mimeType": "application/octet-stream",
                "buffer": attachment_text.encode(),
            }
        )
        send("查看这个附件")
        stored = messages(first_id)[-2]["attachments"][0]
        assert len(stored["extracted_text"]) == 8000 and stored["truncated"]
        expect(page.locator(".attachment-list")).to_contain_text("8000")

        # A stream keeps its original target while the displayed conversation changes.
        api("PATCH", f"/conversations/{first_id}", {"title": "会话 A"})
        page.reload()
        page.wait_for_load_state("networkidle")
        page.locator("textarea.inputbox").fill("[slow] 流式归属测试")
        page.locator("textarea.inputbox").press("Enter")
        expect(page.get_by_role("button", name="停止", exact=True)).to_be_visible()
        page.locator("textarea.inputbox").press("Enter")
        expect(page.locator(".assistant-message").last).to_contain_text("片段0")
        content = page.locator(".content")
        content.evaluate(
            """element => {
                element.scrollTop = Math.max(0, element.scrollHeight-element.clientHeight-120);
            }"""
        )
        expect(page.get_by_role("button", name="回到最新", exact=True)).to_be_visible()
        reading_top = content.evaluate("element => element.scrollTop")
        expect(page.locator(".assistant-message").last).to_contain_text("片段4")
        assert abs(content.evaluate("element => element.scrollTop") - reading_top) < 2
        page.get_by_role("button", name="回到最新", exact=True).click()
        page.wait_for_function(
            """() => { const e=document.querySelector('.content');
                return e.scrollHeight-e.scrollTop-e.clientHeight<2;
            }"""
        )
        active = messages(first_id)[-1]
        page.get_by_role("button", name="新建对话", exact=True).click()
        expect(page.locator(".message-row")).to_have_count(0)
        page.locator("textarea.inputbox").fill("草稿 B")
        page.get_by_role("button", name="停止", exact=True).click()
        wait_finished()
        cancelled = api("GET", f"/messages/{active['id']}")
        assert cancelled["status"] == "cancelled" and cancelled["content"]
        select_conversation("会话 A")
        expect(page.locator(".assistant-message").last).to_contain_text(cancelled["content"])
        assert page.locator("textarea.inputbox").input_value() != "草稿 B"
        page.get_by_role("button", name="新建对话", exact=True).click()
        expect(page.locator("textarea.inputbox")).to_have_value("草稿 B")
        send("第二个会话")
        second_id = next(item["id"] for item in conversations() if item["id"] != first_id)
        assert len(messages(second_id)) == 2

        # Provider failure becomes a saved failed message, never a fake answer.
        send("[fail] 失败状态测试")
        failed = messages(second_id)[-1]
        assert failed["status"] == "failed" and failed["error_code"]
        assert failed["content"] == ""
        expect(page.locator(".assistant-message").last).to_contain_text(failed["error_message"])

        # Regeneration restores the reply's role and removes the later branch.
        old_assistant = messages(second_id)[1]
        send("开发者的新问题")
        page.locator(".content").evaluate("element => { element.scrollTop = 0; }")
        target = page.locator(f'[data-message-id="{old_assistant["id"]}"]')
        target.get_by_role("button", name="重新回复", exact=True).click()
        box = page.locator(".el-message-box")
        expect(box).to_be_visible()
        assert box.bounding_box()["width"] <= 420
        assert abs(box.bounding_box()["x"] + box.bounding_box()["width"] / 2 - 720) < 2
        page.get_by_role("dialog").get_by_role("button", name="重新回复", exact=True).click()
        wait_finished()
        assert len(messages(second_id)) == 2
        assert (
            next(item for item in conversations() if item["id"] == second_id)["current_role_id"]
            == "general"
        )
        last_context = api("GET", "/test/requests")["items"][-1]["messages"]
        assert len(last_context) == 2 and last_context[-1]["content"] == "第二个会话"

        # Duplicate titles remain independent conversations.
        for item_id in (first_id, second_id):
            api("PATCH", f"/conversations/{item_id}", {"title": "同名对话"})
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page.locator(".conversation-item__title", has_text="同名对话")).to_have_count(2)

        snapshot = {
            "session": {
                "旧版会话": [
                    {"role": "user", "content": "旧问题", "roleId": "general"},
                    {"role": "assistant", "content": "旧回答", "roleId": "general"},
                ]
            },
            "sessionRoles": {"旧版会话": "general"},
            "roleContextStart": {"旧版会话": 0},
        }
        settings_command("导入旧记录")
        page.locator('input[type="file"][accept=".json,application/json"]').set_input_files(
            {
                "name": "history.json",
                "mimeType": "application/json",
                "buffer": json.dumps(snapshot, ensure_ascii=False).encode(),
            }
        )
        expect(page.get_by_role("dialog")).to_contain_text("已导入 1 个对话、2 条消息")
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).not_to_be_visible()
        result = api("POST", "/import/local-history", {"snapshot": snapshot})
        assert result["skipped_conversations"] == 1 and result["imported_messages"] == 0

        calls = api("GET", "/test/requests")["items"][calls_before:]
        assert len(calls) == 7, f"Unexpected model calls (double submit?): {len(calls)}"
        assert all(item["model"] == "deepseek-flash" for item in calls)
        assert calls[0]["thinking"]["type"] == "enabled"
        assert calls[1]["thinking"]["type"] == "disabled"
        assert attachment_text[:8000] in calls[1]["messages"][-1]["content"]
        assert TEST_KEY not in page.evaluate("JSON.stringify(localStorage)")
        assert "session" not in page.evaluate("Object.keys(localStorage)")

        # Stopping during reasoning preserves it even before any answer arrives.
        page.get_by_role("button", name="新建对话", exact=True).click()
        page.locator(".model-select").click()
        page.get_by_role("option", name=re.compile("深度思考")).click()
        page.locator("textarea.inputbox").fill("[reasoning-only] 思考阶段停止")
        page.get_by_role("button", name="发送", exact=True).click()
        expect(page.get_by_role("button", name="停止", exact=True)).to_be_visible()
        expect(reasoning_toggle).to_have_attribute("aria-expanded", "false")
        reasoning_toggle.click()
        expect(page.locator(".reasoning-content")).to_contain_text("思考片段4")
        page.get_by_role("button", name="停止", exact=True).click()
        wait_finished()
        reasoning_id = conversations()[0]["id"]
        cancelled = messages(reasoning_id)[-1]
        assert cancelled["status"] == "cancelled" and cancelled["content"] == ""
        assert "思考片段4" in cancelled["reasoning_content"]
        expect(page.locator(".reasoning-content")).to_have_text(cancelled["reasoning_content"])
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(reasoning_toggle).to_have_attribute("aria-expanded", "false")
        reasoning_toggle.click()
        expect(page.locator(".reasoning-content")).to_have_text(cancelled["reasoning_content"])
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.emulate_media(color_scheme="dark")
        page.screenshot(
            path=str(RESULTS / "reasoning-mobile.png"),
            full_page=True,
            animations="disabled",
        )
        page.set_viewport_size({"width": 1440, "height": 960})

        settings_command("API Key 设置")
        page.get_by_role("button", name="清除密钥", exact=True).click()
        assert api("GET", "/credentials/deepseek") == {"configured": False}
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).not_to_be_visible()
        page.screenshot(path=str(RESULTS / "desktop.png"), full_page=True, animations="disabled")
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.get_by_role("button", name="切换会话列表")).to_be_visible()
        page.wait_for_function(
            "document.querySelector('.sideleft').getBoundingClientRect().right <= 1"
        )
        page.get_by_role("button", name="切换会话列表").click()
        expect(page.locator(".sideleft")).to_have_class("sideleft is-mobile-active")
        page.get_by_role("button", name="关闭侧栏", exact=True).click()
        page.wait_for_function(
            "document.querySelector('.sideleft').getBoundingClientRect().right <= 1"
        )
        page.screenshot(path=str(RESULTS / "mobile.png"), full_page=True, animations="disabled")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, "Browser errors: " + json.dumps(errors, ensure_ascii=False)
        browser.close()
        print(
            "Browser regression passed: key, history, attachments, stream target, cancel, drafts, "
            "errors, duplicate titles, idempotent import, safe HTML, reasoning history, "
            "mobile layout."
        )


if __name__ == "__main__":
    run()
