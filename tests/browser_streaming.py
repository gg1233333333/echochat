"""Real timed SSE, progressive display and conversation navigation browser regression."""

import json
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.environ.get("ECHOCHAT_TEST_URL", "http://127.0.0.1:5174")
RESULTS = Path(__file__).resolve().parents[1] / "test-results"
TEST_KEY = "echochat-browser-test-key"
NAV_TITLE = "轮次定位回归"
INSTRUMENT = r"""
localStorage.setItem('echochat.opening.v1', 'seen');
localStorage.setItem('echochat.preferences', JSON.stringify({model:'non-thinking'}));
window.__copied = null;
Object.defineProperty(navigator, 'clipboard', {
    configurable:true, value:{writeText:async text => { window.__copied=text; }}
});
const frame = window.requestAnimationFrame.bind(window);
const cancel = window.cancelAnimationFrame.bind(window);
window.__displayFrames = new Set();
window.requestAnimationFrame = callback => {
    const display = (new Error().stack || '').includes('useStreamingDisplay.js');
    const id = frame(time => { window.__displayFrames.delete(id); callback(time); });
    if (display) window.__displayFrames.add(id);
    return id;
};
window.cancelAnimationFrame = id => { window.__displayFrames.delete(id); cancel(id); };
window.__streamProbe = {events:[],frames:[],base:0};
window.__sampling = false;
const fetchRequest = window.fetch.bind(window);
window.fetch = async (...args) => {
    const response = await fetchRequest(...args);
    if (!(response.headers.get('content-type') || '').includes('text/event-stream'))
        return response;
    const decoder = new TextDecoder();
    let buffer = '';
    const monitor = new TransformStream({transform(bytes, controller) {
        buffer += decoder.decode(bytes, {stream:true});
        let end;
        while ((end = buffer.indexOf('\n\n')) >= 0) {
            const lines = buffer.slice(0,end).split('\n');
            buffer = buffer.slice(end + 2);
            const kind = lines.find(line => line.startsWith('event:'))?.slice(6).trim();
            const data = lines.filter(line => line.startsWith('data:'))
                .map(line => line.slice(5).trimStart()).join('\n');
            if (data) {
                const payload = JSON.parse(data);
                window.__streamProbe.events.push({t:performance.now()-window.__streamProbe.base,
                    kind,content:payload.content || '',message:payload.message || null});
            }
        }
        controller.enqueue(bytes);
    }});
    return new Response(response.body.pipeThrough(monitor),
        {status:response.status,statusText:response.statusText,headers:response.headers});
};
const brokenUnicode = text => {
    for (let index=0; index<text.length; index++) {
        const code = text.charCodeAt(index);
        if (code >= 0xd800 && code <= 0xdbff) {
            const next = text.charCodeAt(++index);
            if (!(next >= 0xdc00 && next <= 0xdfff)) return true;
        } else if (code >= 0xdc00 && code <= 0xdfff) return true;
    }
    return text.includes('\ufffd');
};
window.chatStore = () => document.querySelector('#app').__vue_app__
    .config.globalProperties.$pinia._s.get('chat');
window.startStreamProbe = () => {
    window.__streamProbe = {events:[],frames:[],base:performance.now()};
    window.__sampling = true;
    const tick = () => {
        if (!window.__sampling) return;
        const store = window.chatStore();
        const message = store.messages.at(-1);
        const node = [...document.querySelectorAll('.assistant-message')].at(-1);
        const text = (node?.querySelector('.message-body')?.textContent || '').trimEnd();
        window.__streamProbe.frames.push({t:performance.now()-window.__streamProbe.base,
            text,code:(node?.querySelector('pre code')?.textContent || '').trimEnd(),
            raw:message?.role==='assistant' ? message.content : '',
            status:message?.status || '',currentId:store.currentId,
            revealing:node?.getAttribute('data-revealing')==='true',
            pending:window.__displayFrames.size,broken:brokenUnicode(text)});
        frame(tick);
    };
    frame(tick);
};
window.sampleFrames = count => new Promise(resolve => {
    const tick = () => { if (--count <= 0) resolve(); else frame(tick); };
    frame(tick);
});
"""


def api(context, method, path, data=None):
    response = context.request.fetch(BASE_URL + "/api" + path, method=method, data=data)
    assert response.ok, f"{method} {path}: {response.status} {response.text()}"
    return response.json() if response.status != 204 else None


def ready(page):
    page.wait_for_load_state("networkidle")
    page.wait_for_function("document.querySelector('.echo-app').dataset.openingPhase==='chat'")
    expect(page.locator("textarea.inputbox")).to_be_visible()


def send(page, text):
    page.get_by_role("button", name="新建对话", exact=True).click()
    expect(page.locator(".assistant-message")).to_have_count(0)
    page.locator("textarea.inputbox").fill(text)
    page.evaluate("window.startStreamProbe()")
    page.locator("textarea.inputbox").press("Enter")
    page.wait_for_function("window.__streamProbe.events.some(event=>event.kind==='started')")
    return page.evaluate("window.chatStore().currentId")


def raw_answer(context, conversation_id):
    messages = api(context, "GET", f"/conversations/{conversation_id}/messages")["items"]
    return next(item for item in reversed(messages) if item["role"] == "assistant")


def terminal(page):
    page.wait_for_function(
        "window.__streamProbe.events.some(event=>['done','error'].includes(event.kind))",
        timeout=20000,
    )


def displayed(page, raw):
    page.wait_for_function(
        """expected => {
        const node = document.querySelector('.assistant-message');
        return node && node.getAttribute('data-revealing') !== 'true'
            && (node.querySelector('.message-body').textContent || '').trimEnd()
                ===expected.trimEnd();
    }""",
        arg=raw,
        timeout=10000,
    )
    page.evaluate("window.sampleFrames(2)")


def report(page, name):
    page.evaluate("window.__sampling=false")
    result = page.evaluate("window.__streamProbe")
    assert all(not frame["broken"] for frame in result["frames"]), "Broken Unicode during reveal."
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"streaming-{name}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def check_burst(page, context):
    conversation_id = send(page, "[burst] 检查整段到达后的逐步显示")
    terminal(page)
    saved = raw_answer(context, conversation_id)
    assert saved["status"] == "completed"
    displayed(page, saved["content"])
    result = report(page, "burst")
    first_delta = next(event for event in result["events"] if event["content"])
    first_visible = next(frame for frame in result["frames"] if frame["text"])
    assert first_visible["t"] - first_delta["t"] < 150, (first_delta["t"], first_visible["t"])
    intermediate = {
        frame["text"]
        for frame in result["frames"]
        if frame["text"] and frame["text"] != saved["content"]
    }
    assert len(intermediate) >= 3, "A large SSE delta must reveal in multiple intermediate frames."
    assert all(saved["content"].startswith(text) for text in intermediate)
    done = next(event for event in result["events"] if event["kind"] == "done")
    final = next(frame for frame in result["frames"] if frame["text"] == saved["content"])
    assert final["t"] - done["t"] <= 1100, (final["t"], done["t"])
    assert page.evaluate("window.__displayFrames.size") == 0
    print("PASS burst: timed SSE, intermediate prefixes, timely first text, Unicode, bounded drain")


def check_small_and_stop(page, context):
    conversation_id = send(page, "[slow] 小分块与停止")
    page.wait_for_function("window.__streamProbe.frames.some(frame=>frame.text)")
    textarea = page.locator("textarea.inputbox")
    textarea.fill("继续编辑的草稿🙂")
    textarea.evaluate("element=>element.setSelectionRange(4,4)")
    page.wait_for_function(
        "window.__streamProbe.events.filter(event=>event.kind==='delta'&&event.content).length>=3"
    )
    expect(textarea).to_have_value("继续编辑的草稿🙂")
    assert textarea.evaluate("element=>element.selectionStart") == 4
    page.get_by_role("button", name="停止", exact=True).click()
    expect(page.get_by_role("button", name="发送", exact=True)).to_be_visible()
    saved = raw_answer(context, conversation_id)
    assert saved["status"] == "cancelled"
    displayed(page, saved["content"])
    result = report(page, "small-stop")
    first_delta = next(event for event in result["events"] if event["content"])
    first_visible = next(frame for frame in result["frames"] if frame["text"])
    assert first_visible["t"] - first_delta["t"] < 150
    expect(textarea).to_have_value("继续编辑的草稿🙂")
    assert textarea.evaluate("element=>element.selectionStart") == 4
    assert page.evaluate("window.__displayFrames.size") == 0
    print("PASS small chunks: timely first text, draft/caret retention, stop saves received text")


def check_failure(page, context):
    conversation_id = send(page, "[stream-fail] 收到部分回复后失败")
    terminal(page)
    saved = raw_answer(context, conversation_id)
    assert saved["status"] == "failed" and saved["content"]
    displayed(page, saved["content"])
    expect(page.locator(".message-status.is-error")).to_be_visible()
    assert page.evaluate("window.__displayFrames.size") == 0
    report(page, "failure")
    print("PASS partial failure: received text retained, real error and no pending display RAF")


def check_switch(page, context):
    old_id = send(page, "[burst-hold] 切换期间不会串入旧回复")
    page.wait_for_function("window.__streamProbe.frames.some(frame=>frame.revealing)")
    assert page.evaluate("window.__displayFrames.size") > 0
    textarea = page.locator("textarea.inputbox")
    textarea.fill("旧对话中的后续草稿")
    page.get_by_role("button", name="新建对话", exact=True).click()
    expect(page.locator(".assistant-message")).to_have_count(0)
    new_id = page.evaluate("window.chatStore().currentId")
    assert new_id != old_id
    textarea.fill("新对话的草稿🙂")
    textarea.evaluate("element=>element.setSelectionRange(3,3)")
    page.wait_for_function("window.__displayFrames.size===0")
    page.evaluate("window.sampleFrames(8)")
    expect(page.locator(".assistant-message")).to_have_count(0)
    expect(textarea).to_have_value("新对话的草稿🙂")
    assert textarea.evaluate("element=>element.selectionStart") == 3
    page.get_by_role("button", name="停止", exact=True).click()
    expect(page.get_by_role("button", name="发送", exact=True)).to_be_visible()
    old = raw_answer(context, old_id)
    assert old["status"] == "cancelled" and old["content"]
    report(page, "switch")
    print("PASS conversation switch: old reveal cancelled, no leaked text and new draft retained")


def check_long_code(page, context, scenario="long-code"):
    conversation_id = send(page, f"[{scenario}] 大代码块渐进显示与完整复制")
    terminal(page)
    saved = raw_answer(context, conversation_id)
    assert saved["status"] == "completed"
    expected_code = re.search(r"```python\n([\s\S]*?)\n```", saved["content"]).group(1)
    code = page.locator(".assistant-message pre code")
    expect(code).to_be_visible()
    assert len(code.text_content().rstrip("\n")) < len(expected_code), (
        "Copy test needs a partial presentation."
    )
    page.evaluate("window.__copied=null")
    page.locator(".assistant-message pre .copy-btn").click()
    page.wait_for_function("window.__copied!==null")
    assert page.evaluate("window.__copied").rstrip("\n") == expected_code
    page.wait_for_function(
        """expected => {
        const node=document.querySelector('.assistant-message');
        return node && node.getAttribute('data-revealing')!=='true'
            && node.querySelector('pre code').textContent.trimEnd()===expected;
    }""",
        arg=expected_code,
        timeout=10000,
    )
    page.evaluate("window.sampleFrames(2)")
    result = report(page, scenario)
    lengths = {
        len(frame["code"])
        for frame in result["frames"]
        if 0 < len(frame["code"]) < len(expected_code)
    }
    assert len(lengths) >= 3, f"{scenario}: large code must have multiple intermediate prefixes."
    gaps = [b["t"] - a["t"] for a, b in zip(result["frames"], result["frames"][1:], strict=False)]
    assert max(gaps) < 1500, f"Long-code rendering blocked paint for {max(gaps)}ms."
    assert page.evaluate("window.__displayFrames.size") == 0
    page.reload()
    ready(page)
    expect(code).to_have_text(expected_code + "\n")
    expect(page.locator('.assistant-message[data-revealing="true"]')).to_have_count(0)
    assert page.evaluate("window.__displayFrames.size") == 0
    print(
        f"PASS {scenario}: no prolonged paint freeze, full received copy, "
        "reload renders history immediately"
    )


def nav_snapshot():
    messages = []
    for index in range(24):
        messages.extend(
            [
                {"role": "user", "content": f"导航第 {index + 1} 个问题：解释场景 {index + 1}。"},
                {
                    "role": "assistant",
                    "content": f"第 {index + 1} 个回答：这是实际保存的关联回复。\n\n"
                    + "保持稳定的阅读位置，点击导航只定位已有问题，不发送新的请求。\n\n" * 4,
                },
            ]
        )
    return {
        "session": {NAV_TITLE: messages},
        "sessionRoles": {NAV_TITLE: "general"},
        "roleContextStart": {NAV_TITLE: 0},
    }


def check_navigation(page, context, browser):
    calls = len(api(context, "GET", "/test/requests")["items"])
    api(context, "POST", "/import/local-history", {"snapshot": nav_snapshot()})
    conversation = next(
        item
        for item in api(context, "GET", "/conversations")["items"]
        if item["title"] == NAV_TITLE
    )
    messages = api(context, "GET", f"/conversations/{conversation['id']}/messages")["items"]
    users = [item for item in messages if item["role"] == "user"]
    target = users[10]
    page.reload()
    ready(page)
    page.locator(".conversation-item").filter(
        has=page.locator(".conversation-item__title", has_text=NAV_TITLE)
    ).locator(".conversation-select").click()
    ticks = page.locator(".conversation-navigator__rail button[data-navigation-id]")
    expect(ticks).to_have_count(len(users))
    tick = page.locator(
        f'.conversation-navigator__rail button[data-navigation-id="{target["id"]}"]'
    )
    tick.hover()
    preview = page.locator(".conversation-navigation-preview")
    expect(preview).to_contain_text(target["content"])
    expect(preview).to_contain_text("第 11 个回答")
    tick.click()
    target_row = page.locator(f'.message-row[data-message-id="{target["id"]}"]')
    expect(target_row).to_be_visible()
    expect(tick).to_have_attribute("aria-current", "location")
    assert target_row.bounding_box()["y"] >= page.locator(".content").bounding_box()["y"] - 2
    before = page.locator(".content").evaluate("element=>element.scrollTop")
    page.locator("textarea.inputbox").fill("上滚阅读时编辑草稿")
    page.locator("textarea.inputbox").evaluate("element=>element.setSelectionRange(4,4)")
    page.evaluate("window.sampleFrames(8)")
    assert abs(page.locator(".content").evaluate("element=>element.scrollTop") - before) < 2
    expect(page.get_by_role("button", name="回到最新", exact=True)).to_be_visible()
    assert page.locator("textarea.inputbox").evaluate("element=>element.selectionStart") == 4
    page.screenshot(path=str(RESULTS / "streaming-navigation-desktop.png"), animations="disabled")
    assert len(api(context, "GET", "/test/requests")["items"]) == calls
    textarea = page.locator("textarea.inputbox")
    textarea.fill("[slow] 正在生成时回溯已有轮次")
    page.evaluate("window.startStreamProbe()")
    textarea.press("Enter")
    page.wait_for_function(
        "window.__streamProbe.events.some(event=>event.kind==='delta'&&event.content)"
    )
    tick.click()
    expect(target_row).to_be_visible()
    expect(tick).to_have_attribute("aria-current", "location")
    reading_top = page.locator(".content").evaluate("element=>element.scrollTop")
    received = page.evaluate(
        "window.__streamProbe.events.filter(event=>event.kind==='delta'&&event.content).length"
    )
    textarea.fill("导航阅读时的后续草稿🙂")
    textarea.evaluate("element=>element.setSelectionRange(5,5)")
    page.wait_for_function(
        "count=>window.__streamProbe.events.filter(event=>event.kind==='delta'&&event.content)"
        ".length>=count+4",
        arg=received,
    )
    assert abs(page.locator(".content").evaluate("element=>element.scrollTop") - reading_top) < 2
    expect(textarea).to_have_value("导航阅读时的后续草稿🙂")
    assert textarea.evaluate("element=>element.selectionStart") == 5
    page.get_by_role("button", name="回到最新", exact=True).click()
    page.wait_for_function("""() => {
        const content=document.querySelector('.content');
        return content.scrollHeight-content.clientHeight-content.scrollTop < 2;
    }""")
    active_id = page.evaluate("window.chatStore().activeGeneration.messageId")
    expect(page.locator(f'.message-row[data-message-id="{active_id}"]')).to_be_visible()
    page.get_by_role("button", name="停止", exact=True).click()
    expect(page.get_by_role("button", name="发送", exact=True)).to_be_visible()
    assert page.evaluate("window.__displayFrames.size") == 0
    report(page, "navigation-stream")
    assert len(api(context, "GET", "/test/requests")["items"]) == calls + 1
    mobile = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
    mobile.add_init_script(INSTRUMENT)
    mobile.add_init_script(
        "localStorage.setItem('echochat.preferences',JSON.stringify({currentId:ID,model:'non-thinking'}))".replace(
            "ID", json.dumps(conversation["id"])
        )
    )
    mobile_page = mobile.new_page()
    errors = []
    mobile_page.on("pageerror", lambda error: errors.append(str(error)))
    mobile_page.goto(BASE_URL)
    ready(mobile_page)
    navigation_trigger = mobile_page.get_by_role("button", name="定位对话", exact=True)
    navigation_trigger.click()
    popup = mobile_page.locator(".conversation-navigation-popper.el-popper")
    expect(popup).to_be_visible()
    mobile_page.wait_for_function(
        "document.querySelector('.conversation-navigation-popper.el-popper')"
        "?.contains(document.activeElement)"
    )
    mobile_page.keyboard.press("Escape")
    expect(popup).not_to_be_visible()
    expect(navigation_trigger).to_be_focused()
    mobile_page.evaluate("window.sampleFrames(10)")
    expect(navigation_trigger).to_be_focused()
    navigation_trigger.press("Enter")
    expect(popup).to_be_visible()
    mobile_page.wait_for_function(
        "document.querySelector('.conversation-navigation-popper.el-popper')"
        "?.contains(document.activeElement)"
    )
    popup.locator(f'button[data-navigation-id="{target["id"]}"]').click()
    expect(popup).not_to_be_visible()
    expect(navigation_trigger).to_be_focused()
    mobile_page.evaluate("window.sampleFrames(10)")
    expect(navigation_trigger).to_be_focused()
    expect(mobile_page.locator(f'.message-row[data-message-id="{target["id"]}"]')).to_be_visible()
    mobile_page.screenshot(
        path=str(RESULTS / "streaming-navigation-mobile.png"), animations="disabled"
    )
    assert len(api(context, "GET", "/test/requests")["items"]) == calls + 1
    assert not errors, json.dumps(errors, ensure_ascii=False)
    mobile.close()
    print(
        "PASS round navigation: preview, active marker, mobile entry, no navigation model calls; "
        "incoming SSE preserves reading position and returning to latest works"
    )


def check_reduced(browser):
    context = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    context.add_init_script(INSTRUMENT)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE_URL)
    ready(page)
    conversation_id = send(page, "[burst] 减少动态效果即时显示")
    terminal(page)
    saved = raw_answer(context, conversation_id)
    displayed(page, saved["content"])
    result = report(page, "reduced")
    assert not any(frame["revealing"] for frame in result["frames"])
    assert page.evaluate("window.__displayFrames.size") == 0
    assert not errors, json.dumps(errors, ensure_ascii=False)
    context.close()
    print("PASS reduced motion: immediate canonical display and no display RAF")


def run():
    RESULTS.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        options = {"headless": True}
        if sys.platform == "win32":
            options["channel"] = "msedge"
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        fixture = context.request.get(BASE_URL + "/api/test/requests")
        assert fixture.ok, "Only run against tests/browser_server.py on the isolated ports."
        api(context, "DELETE", "/conversations")
        api(context, "PUT", "/credentials/deepseek", {"api_key": TEST_KEY})
        context.add_init_script(INSTRUMENT)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE_URL)
        ready(page)
        check_burst(page, context)
        check_small_and_stop(page, context)
        check_failure(page, context)
        check_switch(page, context)
        check_long_code(page, context)
        check_long_code(page, context, "short-then-long")
        check_navigation(page, context, browser)
        check_reduced(browser)
        assert not errors, json.dumps(errors, ensure_ascii=False)
        context.close()
        browser.close()


if __name__ == "__main__":
    run()
