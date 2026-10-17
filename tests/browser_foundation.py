"""Local mock-only acceptance for run records, collapsed permissions and provider settings."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("ECHOCHAT_TEST_URL", "http://127.0.0.1:5174")
RESULTS = Path(__file__).resolve().parents[1] / "test-results"


def run():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        errors = []
        for width in (1440, 390, 320):
            context = browser.new_context(viewport={"width": width, "height": 900})
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            assert page.request.put(f"{BASE}/api/provider", data={"base_url": "https://api.deepseek.com/v1", "model": "deepseek-flash", "protocol": "deepseek"}).ok
            assert page.request.put(f"{BASE}/api/credentials/deepseek", data={"api_key": "echochat-browser-test-key"}).ok
            cid = page.request.post(f"{BASE}/api/conversations", data={}).json()["id"]
            context.add_init_script("localStorage.setItem('echochat.opening.v1','seen')")
            context.add_init_script("if (!localStorage.getItem('echochat.preferences')) localStorage.setItem('echochat.preferences', " + json.dumps(json.dumps({"currentId": cid})) + ")")
            page.goto(BASE)
            textbox = page.get_by_role("textbox", name="消息输入")
            expect(textbox).to_be_enabled()
            if width == 1440:
                page.get_by_role("button", name="API Key 已保存，修改配置", exact=True).click()
                key_dialog = page.get_by_role("dialog", name="API Key 设置", exact=True)
                expect(key_dialog.locator(".key-target")).to_contain_text("https://api.deepseek.com/v1")
                changed = page.request.put(f"{BASE}/api/provider", data={
                    "base_url": "http://127.0.0.1:12345/v1", "model": "B", "protocol": "openai",
                })
                assert changed.ok
                key_dialog.get_by_placeholder("输入模型服务 API Key", exact=True).fill("fake-stale-dialog-key")
                key_dialog.get_by_role("button", name="更换密钥", exact=True).click()
                expect(key_dialog.get_by_role("alert")).to_contain_text("模型服务已更改")
                expect(key_dialog.locator(".key-target")).to_contain_text("https://api.deepseek.com/v1")
                assert page.request.get(f"{BASE}/api/credentials/deepseek").json() == {"configured": False}
                key_dialog.get_by_role("button", name="Close this dialog").click()
                page.request.put(f"{BASE}/api/provider", data={"base_url": "https://api.deepseek.com/v1", "model": "deepseek-flash", "protocol": "deepseek"})
                page.request.put(f"{BASE}/api/credentials/deepseek", data={"api_key": "echochat-browser-test-key"})
                page.reload()
                expect(textbox).to_be_enabled()
            expect(page.locator(".tool-permissions")).to_have_count(0)
            trigger = page.get_by_role("button", name="允许使用工具", exact=True)
            trigger.click()
            panel = page.locator(".tool-permissions")
            expect(panel).to_be_visible()
            expect(panel.get_by_role("checkbox")).to_have_count(7)
            panel.locator("label").filter(has_text="生成文件").click()
            bounds = panel.bounding_box()
            assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width + 1
            page.screenshot(animations="disabled", path=str(RESULTS / f"foundation-tools-{width}.png"))
            page.reload()
            expect(textbox).to_be_enabled()
            expect(page.locator(".tool-permissions")).to_have_count(0)
            trigger.click()
            expect(panel.get_by_role("checkbox", name="生成文件", exact=True)).not_to_be_checked()
            panel.locator("label").filter(has_text="生成文件").click()
            panel.get_by_role("button", name="完成", exact=True).click()
            expect(panel).to_have_count(0)
            textbox.click()
            textbox.fill("[agent] 请计算并生成文件")
            textbox.press("Enter")
            expect(page.locator(".tool-artifacts a")).to_be_visible(timeout=20000)
            page.get_by_role("button", name="运行记录", exact=True).click()
            dialog = page.get_by_role("dialog", name="运行记录", exact=True)
            expect(dialog.get_by_role("status")).to_have_text("已完成")
            expect(dialog).to_contain_text("工具结束")
            assert "2 次工具尝试" in dialog.inner_text()
            expect(dialog).to_have_css("opacity", "1")
            page.screenshot(animations="disabled", path=str(RESULTS / f"foundation-run-{width}.png"))
            dialog.get_by_role("button", name="Close this dialog").click()
            page.reload()
            expect(textbox).to_be_enabled()
            page.get_by_role("button", name="运行记录", exact=True).click()
            expect(dialog.get_by_role("status")).to_have_text("已完成")
            dialog.get_by_role("button", name="Close this dialog").click()
            # Use a fresh short conversation so the mobile sidebar is readily reachable.
            if width < 768:
                page.get_by_role("button", name="切换会话列表", exact=True).click()
            page.get_by_role("button", name="设置", exact=True).click()
            page.get_by_role("menuitem", name="模型接口", exact=True).click()
            provider = page.get_by_role("dialog", name="模型接口", exact=True)
            expect(provider.get_by_role("textbox", name="模型名称", exact=True)).to_have_value("deepseek-flash")
            provider.get_by_role("textbox", name="模型服务地址", exact=True).fill("http://127.0.0.1:12345/v1")
            provider.get_by_role("textbox", name="模型名称", exact=True).fill("test-model")
            provider.get_by_role("button", name="保存接口", exact=True).click()
            expect(provider).to_contain_text("重新配置此服务的 API Key")
            page.request.put(f"{BASE}/api/credentials/deepseek", data={"api_key": "echochat-browser-test-key", "target": {"base_url": "http://127.0.0.1:12345/v1", "protocol": "deepseek"}})
            # Saving an unchanged target refreshes the UI's credential state.
            provider.get_by_role("button", name="保存接口", exact=True).click()
            before = len(page.request.get(f"{BASE}/api/test/requests").json()["items"])
            provider.get_by_role("button", name="测试已保存连接", exact=True).click()
            expect(provider).to_contain_text("GET /models 连通")
            after = len(page.request.get(f"{BASE}/api/test/requests").json()["items"])
            assert before == after
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            expect(provider).to_have_css("opacity", "1")
            page.screenshot(animations="disabled", path=str(RESULTS / f"foundation-provider-{width}.png"))
            page.request.put(f"{BASE}/api/provider", data={"base_url": "https://api.deepseek.com/v1", "model": "deepseek-flash", "protocol": "deepseek"})
            context.close()
            print(f"PASS foundation {width}: collapsed permissions, persisted choices, run history/reload, provider save and mock-only GET /models")
        assert not errors, errors
        browser.close()


if __name__ == "__main__":
    RESULTS.mkdir(exist_ok=True)
    run()
