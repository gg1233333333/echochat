"""Tool execution, persisted downloads and responsive layout using the isolated fake backend."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.environ.get("ECHOCHAT_TEST_URL", "http://127.0.0.1:5174")
RESULTS = Path(__file__).resolve().parents[1] / "test-results"


def run():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        assert page.request.get(f"{BASE_URL}/api/test/requests").ok
        page.request.put(f"{BASE_URL}/api/credentials/deepseek",
                         data={"api_key": "echochat-browser-test-key"})
        cid = page.request.post(f"{BASE_URL}/api/conversations", data={}).json()["id"]
        page.add_init_script("localStorage.setItem('echochat.opening.v1','seen')")
        page.add_init_script("localStorage.setItem('echochat.preferences', "
                             + json.dumps(json.dumps({"currentId": cid})) + ")")
        page.goto(BASE_URL)
        textbox = page.get_by_role("textbox", name="消息输入")
        expect(textbox).to_be_enabled()
        toggle = page.get_by_role("button", name="允许使用工具", exact=True)
        expect(toggle).to_have_attribute("aria-pressed", "true")
        textbox.fill("[agent] 请计算 0.1+0.2 并生成文件")
        textbox.press("Enter")
        activity = page.locator(".tool-activity")
        expect(activity.locator(".tool-artifacts a")).to_be_visible(timeout=20000)
        expect(activity.locator(".tool-details")).to_have_js_property("open", False)
        activity.locator(".tool-details > summary").click()
        expect(activity.locator("[data-tool-status=completed]")).to_have_count(2)
        activity.locator(".tool-list li").first.locator("summary").click()
        expect(activity.locator(".tool-payload").first).to_contain_text("0.3")
        with page.expect_download() as download:
            activity.locator(".tool-artifacts a").click()
        assert Path(download.value.path()).read_text(encoding="utf-8") == "# 结果\n0.3"
        for width in (1440, 390, 320):
            page.set_viewport_size({"width": width, "height": 844})
            page.wait_for_timeout(250)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            bounds = page.locator(".composer-frame").bounding_box()
            assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width + 1
            page.screenshot(path=str(RESULTS / f"agent-{width}.png"))
        page.reload()
        expect(page.locator(".tool-artifacts a")).to_be_visible(timeout=10000)
        expect(page.locator(".tool-details")).to_have_js_property("open", False)
        page.locator(".tool-details > summary").click()
        expect(page.locator("[data-tool-status=completed]")).to_have_count(2)
        assert not errors, errors
        requests = page.request.get(f"{BASE_URL}/api/test/requests").json()["items"]
        print(json.dumps({"agent_browser": "passed", "screenshots": [1440, 390, 320],
                          "requests_recorded": len(requests)}, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    RESULTS.mkdir(exist_ok=True)
    run()
