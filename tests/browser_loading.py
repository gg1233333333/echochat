"""Production loading regression: run `npm run build` in frontend, then this script.

Serves frontend/dist on a temporary local port; all API responses are synthetic.
No backend, credentials or model requests are used.
"""

import functools
import http.server
import sys
import threading
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
OPTIONS = {
    "roles": [{"id": "general", "name": "EchoChat", "description": "测试助手"}],
    "modes": [{"value": "thinking", "label": "深度思考"}],
    "attachments": {"extensions": ["txt"]},
}
CODE = 'print("<saved>")\n'


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def run():
    assert (DIST / "index.html").is_file(), "Build frontend before running this test."
    grammars = {path.name for path in (DIST / "assets").glob("*.js")}
    grammars = {name for name in grammars if not name.startswith(("index-", "ui-", "motion-"))}
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Handler, directory=str(DIST)),
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, **({"channel": "msedge"} if sys.platform == "win32" else {}),
            )

            def scenario(*, seen=True, language=None, fail=False):
                context = browser.new_context(viewport={"width": 390, "height": 844})
                if seen:
                    context.add_init_script("localStorage.setItem('echochat.opening.v1', 'seen')")
                context.add_init_script("""Object.defineProperty(navigator, 'clipboard', {
                    value: {writeText: async text => {window.copiedCode = text;}}
                });""")
                page = context.new_page()
                errors, unexpected, downloaded, held = [], [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: downloaded.append(request.url.split("/")[-1]))
                conversation = {
                    "id": "loading-test", "title": "代码示例", "current_role_id": "general",
                    "message_count": 1 if language else 0, "preview": "",
                    "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
                }

                def api(route):
                    path = route.request.url.split("/api/", 1)[1].split("?")[0]
                    if path == "options":
                        result = OPTIONS
                    elif path == "credentials/deepseek":
                        result = {"configured": False}
                    elif path == "conversations":
                        result = {"items": [conversation]} if language else (
                            conversation if route.request.method == "POST" else {"items": []}
                        )
                    elif path == "conversations/loading-test/messages":
                        result = {"has_more": False, "items": [{
                            "id": "answer", "conversation_id": "loading-test", "seq": 1,
                            "role": "assistant", "status": "completed", "reasoning_content": "",
                            "content": f"```{language}\n{CODE}```",
                        }]}
                    else:
                        unexpected.append(path)
                        route.abort()
                        return
                    route.fulfill(json=result)

                page.route("**/api/**", api)
                if language:
                    page.route(f"**/assets/{language}-*.js", lambda route: held.append(route))
                page.goto(url, wait_until="domcontentloaded")
                if not language:
                    selector = "textarea.inputbox" if seen else ".welcome-actions button"
                    expect(page.locator(selector)).to_be_visible()
                    page.wait_for_load_state("networkidle")
                    assert not grammars.intersection(downloaded), downloaded
                else:
                    code = page.locator(".message-body pre code")
                    expect(code).to_have_text(CODE)
                    expect(code.locator("span")).to_have_count(0)
                    assert len(held) == 1, "The grammar must be requested without blocking history."
                    if fail:
                        held[0].abort()
                        page.wait_for_load_state("networkidle")
                        expect(code.locator("span")).to_have_count(0)
                    else:
                        held[0].continue_()
                        expect(code.locator(".hljs-built_in")).to_have_count(1)
                    expect(code).to_have_text(CODE)
                    page.locator(".message-body .copy-btn").click()
                    page.wait_for_function("window.copiedCode !== undefined")
                    assert page.evaluate("window.copiedCode") == CODE
                    requested = grammars.intersection(downloaded)
                    assert len(requested) == 1 and next(iter(requested)).startswith(f"{language}-"), requested
                    if not fail:
                        held.clear()
                        page.reload(wait_until="domcontentloaded")
                        expect(code).to_have_text(CODE)
                        assert len(held) == 1
                        held[0].continue_()
                        expect(code.locator(".hljs-built_in")).to_have_count(1)
                assert not errors, errors
                assert not unexpected, unexpected
                context.close()

            scenario(seen=False)
            scenario()
            scenario(language="python")
            scenario(language="sql", fail=True)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print("PASS production loading: no initial grammars; lazy history highlighting, refresh, copy and failed downloads")


if __name__ == "__main__":
    run()
