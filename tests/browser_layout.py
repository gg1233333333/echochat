"""Responsive UI checks against the isolated browser-test backend on port 5174."""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.environ.get("ECHOCHAT_TEST_URL", "http://127.0.0.1:5174")
RESULTS = Path(__file__).resolve().parents[1] / "test-results"
TEST_KEY = "echochat-browser-test-key"
TITLE = "设计更舒适的聊天界面"
YESTERDAY_TITLE = "昨天的写作讨论"
EARLIER_TITLE = "更早的信息整理"
VIEWPORTS = ((1440, 900), (1920, 1080), (1024, 768), (390, 844), (320, 700), (1440, 560))
ANSWER = """## 让注意力回到对话

**阅读空间**应围绕内容安排。顶部只保留主题和回答方式，侧栏用于快速找到历史对话。

把消息和输入框放在同一套居中内容列里。长回答使用清晰的段落间距，让用户可以沿着正文持续阅读。

### 一体化输入

- 输入文字在上方，附件和语音放在左下方。
- 发送按钮位于同一个容器的右下方。
- 短问题保持紧凑，多行输入再自然增长。

```python
def conversation_title(question):
    return question.strip()[:32]
LONG_EXAMPLE = "LONG_CODE_EXAMPLE"
```

WIDE_TABLE

历史摘要应该显示 **纯文本**，会话标题帮助用户快速找回讨论主题。
""".replace("LONG_CODE_EXAMPLE", "readable_example_" * 24)
TABLE_COLUMNS = [f"字段{index}abcdef123456" for index in range(12)]
ANSWER = ANSWER.replace(
    "WIDE_TABLE",
    "| "
    + " | ".join(TABLE_COLUMNS)
    + " |\n"
    + "| "
    + " | ".join(["---"] * 12)
    + " |\n"
    + "| "
    + " | ".join(["清晰的示例内容abcdef123456"] * 12)
    + " |",
)
ANSWER += "\n\n" + "\n\n".join(
    f"第 {index + 1} 个阅读要点：保持清楚的段落层次，让内容自然展开。"
    "阅读长回答时，页面应保留输入入口，代码与宽表格仅在自身区域滚动。"
    for index in range(24)
)


def rect(page, selector):
    return page.locator(selector).first.bounding_box()


def no_page_overflow(page):
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), (
        "The application must not scroll horizontally."
    )


def assert_sidebar_background(page):
    background = page.locator(".sideleft").evaluate(
        "element => getComputedStyle(element).backgroundColor"
    )
    assert background not in ("transparent", "rgba(0, 0, 0, 0)"), background
    assert "rgba" not in background or background.endswith(", 1)"), background


def open_sidebar(page, width, source="history"):
    if width < 768:
        page.get_by_role("button", name="切换会话列表", exact=True).click()
    elif width < 1200:
        page.get_by_role(
            "button", name="搜索对话" if source == "search" else "历史对话", exact=True
        ).click()
    else:
        return
    expect(page.locator(".mobile-overlay")).to_be_visible()
    page.wait_for_function("document.querySelector('.sideleft').getBoundingClientRect().left >= 0")
    assert_sidebar_background(page)
    assert page.locator(".sideright").evaluate("element => element.inert")


def close_sidebar(page, width, trigger_name, escape=False):
    if escape:
        page.keyboard.press("Escape")
    else:
        page.get_by_role("button", name="关闭侧栏", exact=True).click()
    expect(page.locator(".mobile-overlay")).to_have_count(0)
    expect(page.get_by_role("button", name=trigger_name, exact=True)).to_be_focused()
    assert not page.locator(".sideright").evaluate("element => element.inert")
    if width < 768:
        page.wait_for_function(
            "document.querySelector('.sideleft').getBoundingClientRect().right <= 1"
        )
    else:
        page.wait_for_function(
            "Math.abs(document.querySelector('.sideleft').getBoundingClientRect().width - 72) < 1"
        )


def check_navigation(page, width):
    toggle = page.get_by_role("button", name="切换会话列表", exact=True)
    if width >= 1200:
        assert abs(rect(page, ".sideleft")["width"] - 248) < 1
        toggle.click()
        expect(page.locator(".sidebar.is-compact")).to_have_count(1)
        assert abs(rect(page, ".sideleft")["width"] - 72) < 1
        page.get_by_role("button", name="历史对话", exact=True).click()
        expect(page.locator(".mobile-overlay")).to_be_visible()
        close_sidebar(page, width, "历史对话", escape=True)
        toggle.click()
        expect(page.locator(".sidebar.is-compact")).to_have_count(0)
    elif width >= 768:
        assert abs(rect(page, ".sideleft")["width"] - 72) < 1
        assert abs(rect(page, ".sideleft [data-echo-logo]")["width"] - 30) < 1
        open_sidebar(page, width, "search")
        expect(page.get_by_placeholder("搜索对话")).to_be_focused()
        close_sidebar(page, width, "搜索对话", escape=True)
        open_sidebar(page, width)
        close_sidebar(page, width, "历史对话")
    else:
        assert rect(page, ".sideleft")["x"] < 0
        open_sidebar(page, width)
        close_sidebar(page, width, "切换会话列表", escape=True)
        open_sidebar(page, width)
        close_sidebar(page, width, "切换会话列表")


def check_key_dialog(page, width):
    if width < 768:
        open_sidebar(page, width)
    trigger = page.locator(".sideleft .key-shortcut")
    expect(trigger).to_be_visible()
    assert page.locator(".key-status").inner_text() in {"未配置", "已保存"}
    trigger.click()
    dialog = page.get_by_role("dialog", name="API Key 设置", exact=True)
    expect(dialog).to_be_visible()
    key_input = page.get_by_placeholder("输入 DeepSeek API Key")
    key_input.fill(TEST_KEY)
    expect(key_input).to_have_attribute("type", "password")
    background = dialog.locator(".el-dialog").evaluate(
        "element => getComputedStyle(element).backgroundColor"
    )
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    expect(key_input).to_have_value("")
    expect(trigger).to_be_focused()
    if width < 768:
        close_sidebar(page, width, "切换会话列表")
    return background


def first_send(page, context, empty_id, width):
    textarea = page.locator("textarea.inputbox")
    textarea.evaluate("element => { window.__layoutTextarea = element; }")
    name = f"layout-note-{width}.txt"
    page.locator("input.file-input").set_input_files(
        {"name": name, "mimeType": "text/plain", "buffer": b"A local layout test attachment."}
    )
    expect(page.locator(".attachment-chip")).to_contain_text(name)
    textarea.fill("请说明这份布局测试附件。")
    textarea.press("Enter")
    expect(page.locator(".user-message")).to_be_visible()
    expect(page.locator(".chat-empty")).not_to_be_visible()
    assert page.evaluate("""() => {
        const input = document.querySelector('textarea.inputbox');
        return input === window.__layoutTextarea && document.activeElement === input
            && input.selectionStart === 0 && input.selectionEnd === 0;
    }"""), "Sending the first message must retain the composer's DOM and focus."
    textarea.fill("后续草稿与光标保持原位")
    textarea.evaluate("element => element.setSelectionRange(6, 6)")
    followup = f"followup-{width}.txt"
    page.locator("input.file-input").set_input_files(
        {"name": followup, "mimeType": "text/plain", "buffer": b"Keep this new draft attachment."}
    )
    expect(page.get_by_role("button", name="发送", exact=True)).to_be_visible(timeout=20000)
    expect(textarea).to_have_value("后续草稿与光标保持原位")
    expect(page.locator(".attachment-chip")).to_contain_text(followup)
    assert page.evaluate("""() => {
        const input = document.querySelector('textarea.inputbox');
        return input === window.__layoutTextarea && document.activeElement === input
            && input.selectionStart === 6 && input.selectionEnd === 6;
    }"""), "Streaming must preserve subsequent draft text, caret and attachments."
    result = context.request.get(BASE_URL + f"/api/conversations/{empty_id}/messages")
    assert result.ok, result.text()
    user = next(item for item in result.json()["items"] if item["role"] == "user")
    assert [file["name"] for file in user["attachments"]] == [name]


def check_scroll_follow(page):
    expect(page.locator(".assistant-message .message-body")).to_contain_text("让注意力回到对话")
    page.wait_for_function("""() => {
        const content = document.querySelector('.content');
        return content && content.scrollHeight > content.clientHeight
            && content.scrollHeight - content.clientHeight - content.scrollTop < 2;
    }""")
    content = page.locator(".content")
    content.evaluate("element => { element.scrollTop -= 100; }")
    latest = page.get_by_role("button", name="回到最新", exact=True)
    expect(latest).to_be_visible()
    before = content.evaluate("element => ({top:element.scrollTop,height:element.clientHeight})")
    textarea = page.locator("textarea.inputbox")
    base = textarea.evaluate("element => getComputedStyle(element).height")
    textarea.fill("多行草稿触发布局变化\n" * 12)
    expect(textarea).to_have_css("height", "164px")
    page.wait_for_function(
        """before => {
        const content = document.querySelector('.content');
        return content.clientHeight < before.height && Math.abs(content.scrollTop - before.top) < 2
            && content.scrollHeight - content.clientHeight - content.scrollTop >= 95;
    }""",
        arg=before,
    )
    textarea.fill("")
    expect(textarea).to_have_css("height", base)
    page.wait_for_function(
        """before => {
        const content = document.querySelector('.content');
        return Math.abs(content.clientHeight - before.height) < 2
            && Math.abs(content.scrollTop - before.top) < 2;
    }""",
        arg=before,
    )
    expect(latest).to_be_visible()
    latest.click()
    page.wait_for_function("""() => {
        const content = document.querySelector('.content');
        return content.scrollHeight - content.clientHeight - content.scrollTop < 2;
    }""")
    expect(latest).not_to_be_visible()


def check_mode_menu(page, width, theme):
    title_style = page.locator(".title-rename").evaluate("""element => {
        const style = getComputedStyle(element);
        return {appearance:style.appearance, borders:[style.borderTopWidth,
            style.borderRightWidth,style.borderBottomWidth,style.borderLeftWidth]};
    }""")
    assert title_style == {"appearance": "none", "borders": ["0px"] * 4}, title_style
    page.locator(".model-select .el-select__wrapper").click()
    popup = page.locator(".echo-mode-popper.el-popper")
    dropdown = popup.locator(".el-select-dropdown")
    expect(dropdown).to_be_visible()
    expect(dropdown.locator(".el-select-dropdown__item")).to_have_count(2)
    expect(dropdown.locator(".el-select-dropdown__item.is-selected")).to_have_count(1)
    styles = popup.evaluate("""element => {
        const selected = element.querySelector('.el-select-dropdown__item.is-selected');
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return {background:style.backgroundColor,radius:style.borderRadius,
            width:rect.width,x:rect.x,right:rect.right,
            selected:getComputedStyle(selected).backgroundColor};
    }""")
    assert styles["background"] not in ("rgba(0, 0, 0, 0)", "transparent"), styles
    assert styles["radius"] == "12px", styles
    assert styles["selected"] not in ("rgba(0, 0, 0, 0)", "transparent"), styles
    assert 260 <= styles["width"] <= width - 32 + 1, styles
    assert styles["x"] >= 0 and styles["right"] <= width, styles
    dropdown.screenshot(
        path=str(RESULTS / f"ui-answer-menu-{theme}-{width}-{page.viewport_size['height']}.png"),
        animations="disabled",
    )
    page.keyboard.press("Escape")
    expect(dropdown).not_to_be_visible()
    return styles["background"]


def check_reading_layout(page, width):
    check_scroll_follow(page)
    page.locator(".content").evaluate("element => { element.scrollTop = 0; }")
    expect(page.locator(".assistant-message .message-body")).to_contain_text("让注意力回到对话")
    sizes = page.evaluate("""() => {
        const rect = selector => {
            const r = document.querySelector(selector).getBoundingClientRect();
            return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom};
        };
        const p = document.querySelector('.assistant-message .message-body p');
        const content = document.querySelector('.content');
        return {header:rect('.header'),input:rect('.container'),column:rect('.composer-column'),
            row:rect('.message-row'),canvas:rect('.sideright'),content:rect('.content'),
            font:getComputedStyle(p).fontSize,line:getComputedStyle(p).lineHeight,
            scrollable:content.scrollHeight > content.clientHeight};
    }""")
    assert sizes["header"]["height"] == (56 if width < 768 else 60), sizes
    assert 96 <= sizes["input"]["height"] <= (144 if width < 768 else 132), sizes
    assert abs(sizes["column"]["x"] - sizes["row"]["x"]) < 1, sizes
    assert abs(sizes["column"]["width"] - sizes["row"]["width"]) < 1, sizes
    assert sizes["column"]["width"] <= 840, sizes
    assert sizes["font"] == "16px" and sizes["line"] == "28px", sizes
    assert sizes["scrollable"], sizes
    assert abs(sizes["input"]["bottom"] - sizes["canvas"]["bottom"]) < 2, sizes
    containment = page.evaluate("""() => {
        const body = document.querySelector('.assistant-message .message-body');
        const contained = selector => {
            const element = body.querySelector(selector);
            for (let node = element; node && node !== body; node = node.parentElement) {
                if (['auto','scroll'].includes(getComputedStyle(node).overflowX)) {
                    const rect = node.getBoundingClientRect();
                    return {local:true, width:rect.width, right:rect.right,
                        overflow:node.scrollWidth > node.clientWidth};
                }
            }
            return {local:false};
        };
        return {code:contained('pre'),table:contained('table'),
            right:body.getBoundingClientRect().right};
    }""")
    for kind in ("code", "table"):
        assert containment[kind]["local"], containment
        assert containment[kind]["right"] <= containment["right"] + 1, containment
    assert containment["code"]["overflow"], containment
    assert containment["table"]["overflow"], containment
    no_page_overflow(page)
    textarea = page.locator("textarea.inputbox")
    base = textarea.bounding_box()["height"]
    textarea.fill("多行输入\n" * 12)
    expect(textarea).to_have_css("height", "164px")
    assert rect(page, ".container")["height"] <= 244
    textarea.fill("")
    expect(textarea).to_have_css("height", f"{int(base)}px")
    hint = page.locator(".toolbar-hint")
    if width < 768:
        expect(hint).not_to_be_visible()
    else:
        expect(hint).to_be_visible()
    expect(page.locator(".model-select .el-select__wrapper.is-disabled")).to_have_count(0)
    send = rect(page, '.send-button[aria-label="发送"]')
    expect(page.get_by_role("button", name="发送", exact=True)).to_be_disabled()
    assert send["x"] >= 0 and send["x"] + send["width"] <= width, send
    assert send["y"] + send["height"] <= page.viewport_size["height"], send
    assert page.locator(".role-selector,.role-indicator,.message-role").count() == 0


def check_upload_warning(page, context, width):
    calls = len(context.request.get(BASE_URL + "/api/test/requests").json()["items"])
    page.locator("input.file-input").set_input_files(
        {"name": "bad.exe", "mimeType": "application/octet-stream", "buffer": b"Unsupported file."}
    )
    warning = page.locator(".el-message--warning")
    expect(warning).to_be_visible()
    expect(warning).to_contain_text("文件类型不支持")
    page.wait_for_function("""() => {
        const warning = document.querySelector('.el-message--warning');
        if (!warning) return false;
        const bounds = warning.getBoundingClientRect();
        return bounds.top >= 0 && bounds.left >= 0 && bounds.right <= innerWidth;
    }""")
    surface = warning.evaluate("""element => {
        const style = getComputedStyle(element);
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = 1;
        const context = canvas.getContext('2d');
        context.fillStyle = style.backgroundColor;
        context.fillRect(0,0,1,1);
        return {background:style.backgroundColor,alpha:context.getImageData(0,0,1,1).data[3],
            position:style.position,width:element.getBoundingClientRect().width};
    }""")
    assert surface["alpha"] == 255 and surface["position"] == "fixed", surface
    assert surface["width"] <= width - 32 + 1, surface
    feedback = page.locator(".composer-feedback")
    expect(feedback).to_contain_text("bad.exe 的文件类型不支持")
    expect(page.locator(".attachment-chip")).to_have_count(0)
    if width in (1440, 390):
        page.screenshot(
            path=str(
                RESULTS / f"ui-upload-warning-dark-{width}-{page.viewport_size['height']}.png"
            ),
            full_page=True,
            animations="disabled",
        )
    page.get_by_role("button", name="关闭文件提示", exact=True).click()
    expect(feedback).to_have_count(0)
    no_page_overflow(page)
    assert len(context.request.get(BASE_URL + "/api/test/requests").json()["items"]) == calls


def run():
    RESULTS.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        launch_options = {"headless": True}
        if sys.platform == "win32":
            launch_options["channel"] = "msedge"
        browser = playwright.chromium.launch(**launch_options)
        setup = browser.new_context()
        fixture = setup.request.get(BASE_URL + "/api/test/requests")
        assert fixture.ok, (
            "This test requires tests/browser_server.py; it never uses the real backend."
        )
        reset = setup.request.delete(BASE_URL + "/api/conversations")
        assert reset.ok, reset.text()
        reset_key = setup.request.delete(BASE_URL + "/api/credentials/deepseek")
        assert reset_key.ok, reset_key.text()
        now = datetime.now(timezone(timedelta(hours=8)))
        snapshot = {
            "session": {
                TITLE: [
                    {"role": "user", "content": "怎么改善聊天页面的阅读体验？"},
                    {"role": "assistant", "content": ANSWER},
                ],
                YESTERDAY_TITLE: [{"role": "user", "content": "昨天讨论了写作。"}],
                EARLIER_TITLE: [{"role": "user", "content": "这是一份更早的整理记录。"}],
            },
            "sessionRoles": {TITLE: "general"},
            "roleContextStart": {TITLE: 0},
            "time": {
                TITLE: int((now - timedelta(days=3)).timestamp() * 1000),
                YESTERDAY_TITLE: int((now - timedelta(days=1)).timestamp() * 1000),
                EARLIER_TITLE: int((now - timedelta(days=5)).timestamp() * 1000),
            },
        }
        imported = setup.request.post(
            BASE_URL + "/api/import/local-history", data={"snapshot": snapshot}
        )
        assert imported.ok, imported.text()
        for width, height in VIEWPORTS:
            empty = setup.request.post(BASE_URL + "/api/conversations", data={})
            assert empty.ok, empty.text()
            empty_id = empty.json()["id"]
            context = browser.new_context(
                viewport={"width": width, "height": height},
                has_touch=width < 768,
                color_scheme="light",
                timezone_id="Asia/Taipei",
            )
            context.add_init_script(
                """
                localStorage.setItem('echochat.opening.v1', 'seen');
                localStorage.setItem('echochat.preferences',
                    JSON.stringify({currentId:CURRENT_ID,model:'chat'}));
            """.replace("CURRENT_ID", json.dumps(empty_id))
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
            page.goto(BASE_URL)
            page.wait_for_load_state("networkidle")
            page.wait_for_function(
                "document.querySelector('.echo-app').dataset.openingPhase === 'chat'"
            )
            textarea = page.locator("textarea.inputbox")
            expect(textarea).to_be_visible()
            expect(page.locator(".chat-empty h1")).to_have_text("今天，想一起解决什么？")
            expect(page.locator("#echo-chat-suggestions .inspiration-card")).to_have_count(3)
            empty_box = rect(page, ".container")
            canvas_box = rect(page, ".sideright")
            heading_box = rect(page, ".chat-empty h1")
            cards_box = rect(page, "#echo-chat-suggestions")
            assert (
                abs(empty_box["y"] + empty_box["height"] - canvas_box["y"] - canvas_box["height"])
                < 2
            ), (empty_box, canvas_box)
            assert cards_box["y"] >= heading_box["y"] + heading_box["height"] - 1, (
                heading_box,
                cards_box,
            )
            assert cards_box["y"] + cards_box["height"] <= empty_box["y"] + 1, (
                cards_box,
                empty_box,
            )
            calls = len(setup.request.get(BASE_URL + "/api/test/requests").json()["items"])
            page.locator("#echo-chat-suggestions .inspiration-card").first.click()
            expect(textarea).not_to_have_value("")
            assert len(setup.request.get(BASE_URL + "/api/test/requests").json()["items"]) == calls
            textarea.fill("")
            no_page_overflow(page)
            if (width, height) == (1440, 900):
                page.screenshot(
                    path=str(RESULTS / "ui-empty-light.png"), full_page=True, animations="disabled"
                )
            if width == 390:
                page.screenshot(
                    path=str(RESULTS / "ui-empty-mobile.png"), full_page=True, animations="disabled"
                )
            check_navigation(page, width)
            light_dialog = check_key_dialog(page, width)
            configured = setup.request.put(
                BASE_URL + "/api/credentials/deepseek", data={"api_key": TEST_KEY}
            )
            assert configured.ok, configured.text()
            page.reload()
            page.wait_for_load_state("networkidle")
            page.wait_for_function(
                "document.querySelector('.echo-app').dataset.openingPhase === 'chat'"
            )
            expect(page.locator(".key-status")).to_have_text("已保存")
            first_send(page, context, empty_id, width)
            open_sidebar(page, width)
            headings = page.locator(".history-group__heading").all_text_contents()
            assert set(headings) == {"今天", "昨天", "更早"}, headings
            expect(page.locator(".conversation-item__preview")).to_have_count(0)
            page.get_by_placeholder("搜索对话").fill(TITLE)
            preview = page.locator(".conversation-item__preview")
            expect(preview).to_be_visible()
            assert "**" not in preview.inner_text()
            page.locator(".conversation-item").filter(
                has=page.locator(".conversation-item__title", has_text=TITLE)
            ).locator(".conversation-select").click()
            check_reading_layout(page, width)
            light_menu = check_mode_menu(page, width, "light")
            page.screenshot(
                path=str(RESULTS / f"unified-layout-{width}-{height}.png"),
                full_page=True,
                animations="disabled",
            )
            if (width, height) == (1440, 900):
                page.screenshot(
                    path=str(RESULTS / "ui-long-light.png"), full_page=True, animations="disabled"
                )
            if width == 390:
                page.screenshot(
                    path=str(RESULTS / "ui-mobile.png"), full_page=True, animations="disabled"
                )
            textarea.fill("主题切换后保留草稿")
            page.emulate_media(color_scheme="dark")
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            expect(textarea).to_have_value("主题切换后保留草稿")
            dark_dialog = check_key_dialog(page, width)
            assert light_dialog != dark_dialog, (light_dialog, dark_dialog)
            dark_menu = check_mode_menu(page, width, "dark")
            assert light_menu != dark_menu, (light_menu, dark_menu)
            textarea.fill("")
            page.screenshot(
                path=str(RESULTS / f"unified-dark-{width}-{height}.png"),
                full_page=True,
                animations="disabled",
            )
            if (width, height) == (1440, 900):
                page.screenshot(
                    path=str(RESULTS / "ui-dark.png"), full_page=True, animations="disabled"
                )
            check_upload_warning(page, context, width)
            assert TEST_KEY not in page.evaluate("JSON.stringify(localStorage)")
            assert not errors, json.dumps(errors, ensure_ascii=False)
            print(
                f"PASS {width}x{height}: empty composer, same DOM and draft, column, "
                "local overflow, sidebar focus, masked settings, theme"
            )
            context.close()
        setup.close()
        browser.close()


if __name__ == "__main__":
    run()
