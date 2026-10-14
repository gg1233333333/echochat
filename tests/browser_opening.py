"""Opening-screen regression against an isolated browser-test backend.

Start tests/browser_server.py --port 8001 --frontend-port 5174 and Vite with
its API proxy pointing at port 8001. Override ECHOCHAT_TEST_URL if necessary.
"""

import base64
import json
import math
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.environ.get("ECHOCHAT_TEST_URL", "http://127.0.0.1:5174")
OPENING_KEY = "echochat.opening.v1"
TEST_KEY = "echochat-browser-test-key"
RESULTS = Path(__file__).resolve().parents[1] / "test-results"
PARTICLE_GEOMETRY = """() => Array.from(document.querySelectorAll('.welcome-particle-slot'))
    .map(slot => {
        const layer = slot.parentElement;
        const bounds = layer.getBoundingClientRect();
        const rect = slot.getBoundingClientRect();
        const scaleX = bounds.width / layer.offsetWidth;
        const scaleY = bounds.height / layer.offsetHeight;
        const baseX = bounds.left + parseFloat(slot.style.left) / 100 * bounds.width
            + rect.width / 2;
        const baseY = bounds.top + parseFloat(slot.style.top) / 100 * bounds.height
            + rect.height / 2;
        return {
            baseX, baseY, x: rect.x + rect.width / 2, y: rect.y + rect.height / 2,
            dx: (rect.x + rect.width / 2 - baseX) / scaleX,
            dy: (rect.y + rect.height / 2 - baseY) / scaleY,
        };
    })"""
REVEAL_GEOMETRY = """() => {
    const point = circle => ({
        x: circle.cx.baseVal.value, y: circle.cy.baseVal.value,
        radius: circle.r.baseVal.value, opacity: Number(getComputedStyle(circle).opacity),
    });
    return {
        live: point(document.querySelector('[data-reveal-live]')),
        trail: Array.from(document.querySelectorAll('[data-reveal-trail]'), point),
    };
}"""


def run():
    RESULTS.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        launch_options = {"headless": True}
        if sys.platform == "win32":
            launch_options["channel"] = "msedge"
        browser = playwright.chromium.launch(**launch_options)
        errors = []

        def new_page(width=1440, height=960, *, seen=False, reduced=False):
            context = browser.new_context(
                viewport={"width": width, "height": height},
                reduced_motion="reduce" if reduced else "no-preference",
            )
            context.set_default_timeout(7000)
            if seen:
                context.add_init_script(f"localStorage.setItem({json.dumps(OPENING_KEY)}, 'seen');")
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            return context, page

        control, control_page = new_page(seen=True)

        def api(method, path, data=None):
            response = control.request.fetch(BASE_URL + "/api" + path, method=method, data=data)
            assert response.ok, f"{method} {path}: {response.status} {response.text()}"
            return response.json() if response.status != 204 else None

        # This guard must succeed before any history mutation or key configuration.
        fixture = control.request.get(BASE_URL + "/api/test/requests")
        assert fixture.ok, "Start the isolated tests/browser_server.py before this test."
        calls_before = len(fixture.json()["items"])
        api("DELETE", "/conversations")
        api("PUT", "/credentials/deepseek", {"api_key": TEST_KEY})

        def model_calls():
            return len(api("GET", "/test/requests")["items"])

        def current_id(page):
            return page.evaluate(
                "JSON.parse(localStorage.getItem('echochat.preferences')).currentId"
            )

        def save_brand(page):
            expect(page.locator("[data-echo-logo]")).to_have_count(1)
            expect(page.locator("[data-echo-title]")).to_have_count(1)
            page.evaluate("""() => {
                window.openingBrand = {
                    logo: document.querySelector('[data-echo-logo]'),
                    title: document.querySelector('[data-echo-title]')
                };
            }""")

        def assert_brand(page, target):
            expect(page.locator("[data-echo-logo]")).to_have_count(1)
            expect(page.locator("[data-echo-title]")).to_have_count(1)
            page.wait_for_function(
                """target => {
                const logo = document.querySelector('[data-echo-logo]');
                const title = document.querySelector('[data-echo-title]');
                const host = document.querySelector(target);
                return logo === openingBrand.logo && title === openingBrand.title
                    && host.contains(logo) && host.contains(title);
            }""",
                arg=target,
                timeout=2000,
            )
            expect(page.locator("[data-echo-logo]")).to_be_visible()

        def assert_no_overflow(page):
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                "Page overflowed horizontally."
            )

        def eye_offset(page):
            return page.locator(".echo-eyes").evaluate("""eyes => {
                const center = new DOMPoint(60, 66.5);
                const gaze = center.matrixTransform(eyes.getScreenCTM());
                const neutral = center.matrixTransform(eyes.parentElement.getScreenCTM());
                return { x: gaze.x - neutral.x, y: gaze.y - neutral.y };
            }""")

        def assert_neutral_eyes(page):
            page.wait_for_function("""() => {
                const eyes = document.querySelector('.echo-eyes');
                const center = new DOMPoint(60, 66.5);
                const gaze = center.matrixTransform(eyes.getScreenCTM());
                const neutral = center.matrixTransform(eyes.parentElement.getScreenCTM());
                return Math.hypot(gaze.x - neutral.x, gaze.y - neutral.y) < 0.1;
            }""")

        def particles(page):
            points = page.evaluate(PARTICLE_GEOMETRY)
            assert len(points) == 23, "The opening background lost its particle layer."
            return points

        def assert_neutral_particles(page):
            page.wait_for_function(
                f"() => ({PARTICLE_GEOMETRY})().every(point => "
                "Math.hypot(point.dx, point.dy) < 0.5)"
            )

        def reveal(page):
            return page.evaluate(REVEAL_GEOMETRY)

        def assert_hidden_reveal(page, timeout=2000):
            page.wait_for_function(
                f"() => {{ const field = ({REVEAL_GEOMETRY})(); "
                "return [field.live, ...field.trail].every(point => point.opacity < 0.001); }",
                timeout=timeout,
            )

        def assert_pattern_visible(page, pointer):
            # Compare rendered pixels with just the revealed artwork removed, so a
            # pointer glow or changed JavaScript state cannot satisfy this check.
            pattern = page.locator(".welcome-reveal-pattern")
            decorations = page.locator(".welcome-composition, [data-inspiration]").evaluate_all(
                "elements => elements.map(element => { "
                "const rect = element.getBoundingClientRect(); "
                "return { left: rect.left - 20, right: rect.right + 20, "
                "top: rect.top - 20, bottom: rect.bottom + 20 }; })"
            )
            visible = page.screenshot()
            original_visibility = pattern.evaluate("element => element.style.visibility")
            pattern.evaluate("element => element.style.visibility = 'hidden'")
            try:
                hidden = page.screenshot()
            finally:
                pattern.evaluate(
                    "(element, visibility) => element.style.visibility = visibility",
                    original_visibility,
                )
            difference = page.evaluate(
                """async ({ visible, hidden, pointer, decorations }) => {
                    const decode = async data => {
                        const image = new Image();
                        image.src = 'data:image/png;base64,' + data;
                        await image.decode();
                        const canvas = document.createElement('canvas');
                        canvas.width = image.width;
                        canvas.height = image.height;
                        const context = canvas.getContext('2d');
                        context.drawImage(image, 0, 0);
                        return { width: image.width, pixels:
                            context.getImageData(0, 0, image.width, image.height).data };
                    };
                    const before = await decode(visible);
                    const after = await decode(hidden);
                    let local = 0, distant = 0;
                    for (let index = 0; index < before.pixels.length; index += 4) {
                        const delta = Math.max(...[0, 1, 2].map(channel => Math.abs(
                            before.pixels[index + channel] - after.pixels[index + channel]
                        )));
                        if (delta < 25) continue;
                        const pixel = index / 4;
                        const x = pixel % before.width;
                        const y = Math.floor(pixel / before.width);
                        const distance = Math.hypot(x - pointer.x, y - pointer.y);
                        if (distance < 205) local++;
                        else if (distance > 230 && !decorations.some(rect =>
                            x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom
                        )) distant++;
                    }
                    return { local, distant };
                }""",
                {
                    "visible": base64.b64encode(visible).decode(),
                    "hidden": base64.b64encode(hidden).decode(),
                    "pointer": pointer,
                    "decorations": decorations,
                },
            )
            assert difference["local"] > 300, (
                f"Pointer did not reveal a clear background pattern: {difference}."
            )
            assert difference["distant"] < difference["local"] * 0.1 + 40, (
                f"Hidden artwork leaked outside the local pointer field: {difference}."
            )
            page.screenshot(path=str(RESULTS / "opening-background-reveal.png"))

        def assert_background_reveal(page):
            layer = page.locator(".welcome-reveal")
            expect(layer).to_have_count(1)
            assert layer.evaluate("element => getComputedStyle(element).pointerEvents") == "none"
            assert layer.locator(".welcome-reveal-pattern path").count() > 2
            assert len(reveal(page)["trail"]) == 6
            page.evaluate("window.dispatchEvent(new Event('blur'))")
            assert_hidden_reveal(page)
            pointer = {"x": 1100, "y": 160}
            page.mouse.move(pointer["x"], pointer["y"])
            page.wait_for_function(f"() => ({REVEAL_GEOMETRY})().live.opacity > 0.95")
            page.wait_for_timeout(750)
            field = reveal(page)
            assert abs(field["live"]["x"] - pointer["x"]) < 1
            assert abs(field["live"]["y"] - pointer["y"]) < 1
            assert 175 <= field["live"]["radius"] <= 220
            assert_pattern_visible(page, pointer)
            for x, y in ((1030, 210), (950, 240), (870, 270), (790, 300)):
                page.mouse.move(x, y)
                page.wait_for_timeout(80)
            moving = reveal(page)
            active = [point for point in moving["trail"] if point["opacity"] > 0.05]
            assert len(active) >= 3, "Moving pointer did not leave a fading reveal trail."
            assert max(point["x"] for point in active) - min(point["x"] for point in active) > 100
            trail_positions = [(point["x"], point["y"]) for point in moving["trail"]]
            page.wait_for_timeout(1500)
            stationary = reveal(page)
            assert stationary["live"]["opacity"] > 0.95
            assert all(point["opacity"] < 0.001 for point in stationary["trail"]), (
                "A stationary pointer kept adding new trail points."
            )
            assert [(point["x"], point["y"]) for point in stationary["trail"]] == trail_positions
            page.evaluate("window.dispatchEvent(new PointerEvent('pointerout'))")
            page.wait_for_timeout(100)
            assert 0 < reveal(page)["live"]["opacity"] < 0.95, (
                "Pointer exit should fade the revealed background instead of snapping."
            )
            assert_hidden_reveal(page)
            page.mouse.move(pointer["x"], pointer["y"])
            page.wait_for_function(f"() => ({REVEAL_GEOMETRY})().live.opacity > 0.95")
            page.locator(".welcome-stage").dispatch_event(
                "pointermove", {"pointerType": "touch", "clientX": 1100, "clientY": 160}
            )
            assert_hidden_reveal(page, timeout=500)

        def assert_particle_reaction(page):
            # Subtract the layer's parallax so this checks local background interaction.
            page.evaluate("window.dispatchEvent(new Event('blur'))")
            assert_neutral_particles(page)
            page.wait_for_timeout(750)
            initial = particles(page)
            near = initial[0]
            pointer = {"x": near["baseX"] - 45, "y": near["baseY"] - 28}
            far_index = max(
                range(len(initial)),
                key=lambda index: math.hypot(
                    initial[index]["baseX"] - pointer["x"],
                    initial[index]["baseY"] - pointer["y"],
                ),
            )
            page.mouse.move(pointer["x"], pointer["y"])
            page.wait_for_function(
                f"() => Math.hypot(({PARTICLE_GEOMETRY})()[0].dx, "
                f"({PARTICLE_GEOMETRY})()[0].dy) > 10"
            )
            page.wait_for_timeout(400)
            moved = particles(page)
            nearby = moved[0]
            assert nearby["dx"] > 0 and nearby["dy"] > 0, (
                f"Nearby particle did not retreat from the pointer: {nearby}."
            )
            assert 10 < math.hypot(nearby["dx"], nearby["dy"]) <= 28.1, (
                f"Local particle movement was too weak or exceeded its limit: {nearby}."
            )
            distant = moved[far_index]
            assert math.hypot(distant["dx"], distant["dy"]) < 0.5, (
                f"A far-away particle was affected by the local pointer field: {distant}."
            )
            assert all(math.hypot(point["dx"], point["dy"]) <= 28.1 for point in moved)
            # Let whole-layer parallax settle before checking same-point accumulation.
            stable_offsets = []
            for _ in range(3):
                for _ in range(8):
                    page.evaluate(
                        "point => window.dispatchEvent(new PointerEvent('pointermove', "
                        "{pointerType: 'mouse', clientX: point.x, clientY: point.y}))",
                        pointer,
                    )
                page.wait_for_timeout(750)
                stable_offsets.append(particles(page)[0])
            before, repeated = stable_offsets[-2:]
            assert math.hypot(repeated["dx"] - before["dx"], repeated["dy"] - before["dy"]) < 1
            page.evaluate("window.dispatchEvent(new PointerEvent('pointerout'))")
            assert_neutral_particles(page)
            page.mouse.move(pointer["x"] + 2, pointer["y"] + 2)
            page.wait_for_function(f"() => ({PARTICLE_GEOMETRY})()[0].dx > 5")
            page.evaluate("window.dispatchEvent(new Event('blur'))")
            assert_neutral_particles(page)

        def start_tracked_entry(page):
            page.evaluate("""() => {
                window.openingMotion = [];
                window.openingMotionDone = false;
                document.querySelector('.welcome-start').addEventListener('click', () => {
                    const start = performance.now();
                    const sample = () => {
                        const logo = document.querySelector('[data-echo-logo]');
                        const bounds = logo.getBoundingClientRect();
                        const phase = document.querySelector('.echo-app').dataset.openingPhase;
                        const cards = Array.from(document.querySelectorAll('[data-inspiration]'))
                            .map(card => {
                                const rect = card.getBoundingClientRect();
                                return {
                                    x: rect.x, y: rect.y, width: rect.width, height: rect.height,
                                };
                            });
                        const nav = document.querySelector('.sideleft');
                        const canvas = document.querySelector('.sideright');
                        openingMotion.push({
                            x: bounds.x, y: bounds.y, width: bounds.width, phase, cards,
                            t: performance.now()-start,
                            navAlpha: Number(getComputedStyle(nav, '::before').opacity),
                            canvasMask: getComputedStyle(canvas, '::before').maskImage,
                        });
                        if (phase !== 'chat' && performance.now() - start < 4000)
                            requestAnimationFrame(sample);
                        else openingMotionDone = true;
                    };
                    requestAnimationFrame(sample);
                }, { once: true, capture: true });
            }""")
            page.get_by_role("button", name="开始对话", exact=True).click()

        def assert_smooth_entry(page):
            page.wait_for_function("openingMotionDone")
            frames = page.evaluate("openingMotion")
            first, last = frames[0], frames[-1]
            assert 1150 <= last["t"] <= 1900, "Entry must glide without an abrupt short cut."
            entering = [frame for frame in frames if frame["phase"] == "entering"]
            assert any(0.05 < frame["navAlpha"] < 0.95 for frame in entering), (
                "The navigation background must fade in rather than appearing at once."
            )
            assert any("linear-gradient" in frame["canvasMask"] for frame in entering), (
                "The reading canvas must use a soft reveal edge."
            )
            distance = math.hypot(last["x"] - first["x"], last["y"] - first["y"])
            assert distance > first["width"] * 0.5, (
                f"Robot did not travel from the core to the brand dock: {first}, {last}."
            )
            intermediate = [
                frame
                for frame in frames
                if 0.08
                < math.hypot(frame["x"] - first["x"], frame["y"] - first["y"]) / distance
                < 0.92
            ]
            assert len(intermediate) >= 8, "Robot stayed still and jumped to the dock."
            assert all(last["width"] < frame["width"] < first["width"] for frame in intermediate), (
                "Robot did not shrink continuously while moving."
            )
            jumps = [
                math.hypot(after["x"] - before["x"], after["y"] - before["y"])
                for before, after in zip(frames[:-1], frames[1:], strict=True)
            ]
            assert max(jumps) < distance * 0.15, "Robot jumped abruptly between frames."
            before_finish = next(
                frame for frame in reversed(frames) if frame["phase"] == "entering"
            )
            for before, after in zip(before_finish["cards"], last["cards"], strict=True):
                assert all(abs(before[key] - after[key]) < 1 for key in before), (
                    "Suggestion cards snapped into position at the end of the transition."
                )

        def assert_brand_in_expansion(page, target="#echo-header-brand"):
            page.wait_for_function(
                """target => {
                const logo = document.querySelector('[data-echo-logo]');
                return document.querySelector(target)?.contains(logo);
            }""",
                arg=target,
            )
            assert page.locator(".echo-app").get_attribute("data-opening-phase") == "entering"
            assert page.locator("[data-echo-logo]").evaluate("""element => {
                for (let node = element; node; node = node.parentElement) {
                    const style = getComputedStyle(node);
                    if (style.display === 'none' || style.visibility === 'hidden'
                        || Number(style.opacity) === 0) return false;
                }
                return true;
            }"""), "The moving brand was hidden by one of its ancestors."

        def ready(page, timeout=6000):
            expect(page.locator(".welcome-stage")).to_have_count(0, timeout=timeout)
            expect(page.locator(".echo-app")).to_have_attribute("data-opening-phase", "chat")
            expect(page.locator(".app-shell")).not_to_have_attribute("inert", "")
            expect(page.locator("textarea.inputbox")).to_be_enabled(timeout=timeout)
            expect(page.locator("textarea.inputbox")).to_be_visible()

        def opening(page):
            page.goto(BASE_URL, wait_until="domcontentloaded")
            expect(page.locator(".welcome-stage")).to_be_visible()
            expect(page.get_by_role("button", name="直接进入", exact=True)).to_have_count(0)
            expect(page.locator(".welcome-wordmark, .welcome-footer")).to_have_count(0)
            expect(page.locator(".echo-app")).to_have_attribute("data-opening-phase", "welcome")
            expect(page.locator(".app-shell")).to_have_attribute("inert", "")
            assert page.evaluate(f"localStorage.getItem({json.dumps(OPENING_KEY)})") is None
            assert_hidden_reveal(page)
            assert_no_overflow(page)

        def enter(page):
            start = page.get_by_role("button", name="开始对话", exact=True)
            expect(start).to_be_enabled(timeout=3000)
            start.click()
            ready(page)
            assert page.evaluate(f"localStorage.getItem({json.dumps(OPENING_KEY)})") == "seen"

        def settings(page, command):
            toggle = page.get_by_role(
                "button", name="切换会话列表", exact=True, include_hidden=True
            )
            if toggle.get_attribute("aria-expanded") != "true":
                toggle.click()
            page.get_by_role("button", name="设置", exact=True).click()
            item = page.get_by_role("menuitem", name=re.compile(command))
            expect(item).to_be_visible()
            return item

        # Blinking and looking at the pointer must animate independently.
        blink_context, blink_page = new_page()
        opening(blink_page)
        blink_page.mouse.move(1200, 300)
        blink_page.wait_for_function(
            """() => {
            const blink = document.querySelector('.echo-eye-blink');
            return new DOMMatrix(getComputedStyle(blink).transform).d < 0.4;
        }""",
            timeout=3000,
        )
        assert eye_offset(blink_page)["x"] > 2, "Blinking overwrote the robot's gaze."
        blink_context.close()

        # First visit waits for the user's decision, then morphs the same brand DOM.
        first_context, page = new_page()
        opening(page)
        save_brand(page)
        expect(page.get_by_role("button", name="开始对话", exact=True)).to_be_enabled(timeout=3000)
        page.wait_for_timeout(300)
        assert page.evaluate(f"localStorage.getItem({json.dumps(OPENING_KEY)})") is None
        assert_particle_reaction(page)
        assert_background_reveal(page)
        logo = page.locator("[data-echo-logo]").bounding_box()
        center_x = logo["x"] + logo["width"] / 2
        center_y = logo["y"] + logo["height"] * 66.5 / 120
        card_before = page.locator("[data-inspiration]").first.bounding_box()
        for dx, dy, axis, sign in (
            (300, 0, "x", 1),
            (-300, 0, "x", -1),
            (0, -250, "y", -1),
            (0, 250, "y", 1),
        ):
            page.mouse.move(center_x + dx, center_y + dy)
            page.wait_for_timeout(250)
            gaze = eye_offset(page)
            assert gaze[axis] * sign > 2, (
                f"Robot looked in the wrong direction at ({dx}, {dy}): {gaze}."
            )
            assert abs(gaze["x"]) < 7 and abs(gaze["y"]) < 5
            assert page.locator(".echo-eyes").evaluate("""eyes => {
                const pupils = eyes.getBoundingClientRect();
                const face = document.querySelector('.echo-face').getBoundingClientRect();
                return pupils.left >= face.left && pupils.right <= face.right
                    && pupils.top >= face.top && pupils.bottom <= face.bottom;
            }"""), "The gaze moved outside the robot's face."
        page.mouse.move(1200, 760)
        page.wait_for_timeout(650)
        card_after = page.locator("[data-inspiration]").first.bounding_box()
        assert (
            math.hypot(card_after["x"] - card_before["x"], card_after["y"] - card_before["y"]) > 8
        )
        assert page.locator(".welcome-pointer-glow").evaluate(
            "element => Number(getComputedStyle(element).opacity) > 0.9"
        ), "Pointer lighting did not appear."
        page.evaluate("""() => {
            window.dispatchEvent(new PointerEvent('pointermove', {clientX: 1300, clientY: 800}));
            window.dispatchEvent(new Event('blur'));
        }""")
        assert_neutral_eyes(page)
        assert_neutral_particles(page)
        page.wait_for_timeout(250)
        assert_neutral_eyes(page)
        assert_neutral_particles(page)
        page.locator(".welcome-stage").dispatch_event(
            "pointermove", {"pointerType": "touch", "clientX": 1300, "clientY": 800}
        )
        page.wait_for_timeout(250)
        assert_neutral_eyes(page)
        assert_neutral_particles(page)
        page.mouse.move(950, 310)
        page.screenshot(path=str(RESULTS / "opening-desktop.png"), animations="disabled")
        before_enter = api("GET", "/conversations?include_empty=true")["items"]
        start_tracked_entry(page)
        assert_hidden_reveal(page, timeout=500)
        entering_particles = particles(page)
        page.evaluate(
            "point => window.dispatchEvent(new PointerEvent('pointermove', "
            "{pointerType: 'mouse', clientX: point.baseX - 45, clientY: point.baseY - 28}))",
            entering_particles[0],
        )
        page.wait_for_timeout(250)
        exiting_particles = particles(page)
        assert_hidden_reveal(page, timeout=500)
        assert all(
            math.hypot(before["dx"] - after["dx"], before["dy"] - after["dy"]) < 0.5
            for before, after in zip(entering_particles, exiting_particles, strict=True)
        ), "Particle interaction continued during the chat transition."
        ready(page)
        expect(page.locator(".welcome-reveal")).to_have_count(0)
        assert_smooth_entry(page)
        assert_brand(page, "#echo-sidebar-brand")
        page.mouse.move(1000, 800)
        assert_neutral_eyes(page)
        assert api("GET", "/conversations?include_empty=true")["items"] == before_enter
        suggestions = page.locator("#echo-chat-suggestions [data-inspiration]")
        expect(suggestions).to_have_count(3)
        for suggestion in suggestions.all():
            expect(suggestion).to_be_visible()
            assert suggestion.evaluate("""element => [
                'position', 'top', 'left', 'width', 'height', 'transform',
                'visibility', 'opacity', 'padding', 'gridArea'
            ].every(property => element.style[property] === '')"""), (
                "Suggestion retained temporary Flip positioning or visibility styles."
            )
        suggestions.first.click()
        expect(page.locator("textarea.inputbox")).not_to_have_value("")
        assert model_calls() == calls_before, "Opening or suggestion caused a model request."
        page.screenshot(path=str(RESULTS / "opening-workspace.png"), animations="disabled")

        # Returning visits use only a short entrance, with no full welcome stage.
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(".welcome-stage")).to_have_count(0)
        expect(page.locator(".echo-app")).to_have_attribute(
            "data-opening-phase", "chat", timeout=700
        )
        ready(page, timeout=1200)
        assert page.evaluate(f"localStorage.getItem({json.dumps(OPENING_KEY)})") == "seen"

        # Brand follows sidebar collapse and responsive layout without being cloned.
        save_brand(page)
        page.get_by_role("button", name="切换会话列表", exact=True).click()
        assert_brand(page, "#echo-sidebar-brand")
        expect(page.locator(".sidebar")).to_have_class(re.compile("is-compact"))
        page.get_by_role("button", name="切换会话列表", exact=True).click()
        assert_brand(page, "#echo-sidebar-brand")
        page.set_viewport_size({"width": 390, "height": 844})
        assert_brand(page, "#echo-header-brand")
        assert_no_overflow(page)
        page.set_viewport_size({"width": 1440, "height": 960})
        assert_brand(page, "#echo-sidebar-brand")

        # The remaining main entry control is fully keyboard operable.
        keyboard_context, keyboard_page = new_page()
        opening(keyboard_page)
        save_brand(keyboard_page)
        start = keyboard_page.get_by_role("button", name="开始对话", exact=True)
        expect(start).to_be_enabled(timeout=3000)
        start.focus()
        expect(start).to_be_focused()
        start.press("Enter")
        ready(keyboard_page)
        assert_brand(keyboard_page, "#echo-sidebar-brand")
        assert keyboard_page.evaluate(f"localStorage.getItem({json.dumps(OPENING_KEY)})") == "seen"
        keyboard_context.close()

        # Seed real stored history through the fixture API; replay must preserve it.
        snapshot = {
            "session": {
                "开场回归历史": [
                    {"role": "user", "content": "已经聊过的问题", "roleId": "general"},
                    {
                        "role": "assistant",
                        "content": "已经保存的回答",
                        "roleId": "general",
                    },
                ]
            },
            "sessionRoles": {"开场回归历史": "general"},
            "roleContextStart": {"开场回归历史": 0},
        }
        api("POST", "/import/local-history", {"snapshot": snapshot})
        page.reload(wait_until="networkidle")
        ready(page)
        page.get_by_role("button", name="开场回归历史", exact=True).click()
        expect(page.locator(".assistant-message")).to_contain_text("已经保存的回答")
        page.locator("textarea.inputbox").fill("重播前的草稿")
        page.locator('input[type="file"][multiple]').set_input_files(
            {
                "name": "draft.txt",
                "mimeType": "text/plain",
                "buffer": b"draft attachment",
            }
        )
        expect(page.locator(".attachment-name")).to_have_text("draft.txt")
        old_id = current_id(page)
        history_before = api("GET", "/conversations?include_empty=true")
        messages_before = api("GET", f"/conversations/{old_id}/messages")
        key_before = api("GET", "/credentials/deepseek")
        save_brand(page)
        settings(page, "重播开场").click()
        expect(page.locator(".welcome-stage")).to_be_visible()
        expect(page.locator(".app-shell")).to_have_attribute("inert", "")
        expect(page.locator(".welcome-stage")).to_be_focused()
        expect(page.get_by_role("button", name="开始对话", exact=True)).to_be_enabled(timeout=3000)
        assert_particle_reaction(page)
        assert_background_reveal(page)
        enter(page)
        assert_brand(page, "#echo-sidebar-brand")
        assert current_id(page) == old_id
        expect(page.locator("textarea.inputbox")).to_have_value("重播前的草稿")
        expect(page.locator(".attachment-name")).to_have_text("draft.txt")
        expect(page.locator("#echo-chat-suggestions [data-inspiration]")).to_have_count(0)
        assert api("GET", "/conversations?include_empty=true") == history_before
        assert api("GET", f"/conversations/{old_id}/messages") == messages_before
        assert api("GET", "/credentials/deepseek") == key_before
        assert model_calls() == calls_before
        assert TEST_KEY not in page.evaluate("JSON.stringify(localStorage)")

        # During a reply the replay command is disabled, leaving stream ownership intact.
        page.locator("textarea.inputbox").fill("[slow] 开场期间的生成保护")
        page.get_by_role("button", name="发送", exact=True).click()
        expect(page.get_by_role("button", name="停止", exact=True)).to_be_visible()
        replay = settings(page, "重播开场")
        expect(replay).to_have_attribute("aria-disabled", "true")
        page.keyboard.press("Escape")
        expect(page.locator(".welcome-stage")).to_have_count(0)
        page.get_by_role("button", name="停止", exact=True).click()
        expect(page.get_by_role("button", name="发送", exact=True)).to_be_visible(timeout=10000)
        assert model_calls() == calls_before + 1

        # A collapsed desktop receives the shared logo in its compact navigation rail.
        page.get_by_role("button", name="切换会话列表", exact=True).click()
        page.set_viewport_size({"width": 390, "height": 844})
        settings(page, "重播开场").click()
        expect(page.locator(".welcome-stage")).to_be_visible()
        page.set_viewport_size({"width": 1440, "height": 960})
        expect(page.get_by_role("button", name="开始对话", exact=True)).to_be_enabled(timeout=3000)
        page.get_by_role("button", name="开始对话", exact=True).click()
        assert_brand_in_expansion(page, "#echo-sidebar-brand")
        ready(page)
        assert_brand(page, "#echo-sidebar-brand")
        page.get_by_role("button", name="切换会话列表", exact=True).click()
        assert_brand(page, "#echo-sidebar-brand")

        # Narrow screens and a resize during the transition always land in usable UI.
        for width, height in ((390, 844), (320, 568)):
            mobile_context, mobile = new_page(width, height)
            opening(mobile)
            save_brand(mobile)
            expect(mobile.get_by_role("button", name="开始对话", exact=True)).to_be_enabled(
                timeout=3000
            )
            mobile.wait_for_timeout(900)
            mobile.screenshot(
                path=str(RESULTS / f"opening-mobile-{width}.png"), animations="disabled"
            )
            start_tracked_entry(mobile)
            assert_brand_in_expansion(mobile)
            ready(mobile)
            assert_smooth_entry(mobile)
            assert_brand(mobile, "#echo-header-brand")
            assert_no_overflow(mobile)
            mobile.get_by_role("button", name="切换会话列表", exact=True).click()
            expect(mobile.get_by_role("button", name="设置", exact=True)).to_be_visible()
            settings(mobile, "重播开场").click()
            expect(mobile.locator(".welcome-stage")).to_be_visible()
            expect(mobile.locator(".mobile-overlay")).to_have_count(0)
            expect(mobile.get_by_role("button", name="开始对话", exact=True)).to_be_enabled(
                timeout=3000
            )
            mobile.get_by_role("button", name="开始对话", exact=True).click()
            assert_brand_in_expansion(mobile)
            ready(mobile)
            assert_brand(mobile, "#echo-header-brand")
            expect(mobile.locator(".mobile-overlay")).to_have_count(0)
            mobile.wait_for_function(
                "document.querySelector('.sideleft').getBoundingClientRect().right <= 1"
            )
            expect(mobile.locator("textarea.inputbox")).to_be_focused()
            mobile.locator("textarea.inputbox").fill("手机重播后可以继续输入")
            expect(mobile.locator("textarea.inputbox")).to_have_value("手机重播后可以继续输入")
            assert model_calls() == calls_before + 1
            assert_no_overflow(mobile)
            mobile.screenshot(
                path=str(RESULTS / f"opening-mobile-workspace-{width}.png"),
                animations="disabled",
            )
            mobile_context.close()

        resize_context, resize_page = new_page()
        opening(resize_page)
        save_brand(resize_page)
        expect(resize_page.get_by_role("button", name="开始对话", exact=True)).to_be_enabled(
            timeout=3000
        )
        resize_page.get_by_role("button", name="开始对话", exact=True).click()
        resize_page.set_viewport_size({"width": 390, "height": 844})
        ready(resize_page)
        assert_brand(resize_page, "#echo-header-brand")
        assert_no_overflow(resize_page)
        resize_context.close()

        # Reduced motion stays still and entering is a short fade; changes apply live.
        reduced_context, reduced = new_page(reduced=True)
        opening(reduced)
        save_brand(reduced)
        expect(reduced.get_by_role("button", name="开始对话", exact=True)).to_be_enabled(
            timeout=1000
        )
        assert reduced.evaluate("""() => document.getAnimations().every(animation =>
            animation.playState !== 'running'
                || animation.effect.getComputedTiming().iterations !== Infinity)
        """), "Reduced motion still contains a running perpetual animation."
        reduced.wait_for_timeout(250)
        assert_neutral_eyes(reduced)
        assert_neutral_particles(reduced)
        assert_hidden_reveal(reduced, timeout=500)
        core_before = reduced.locator("[data-echo-logo]").bounding_box()
        reduced.mouse.move(1200, 180)
        reduced.wait_for_timeout(250)
        core_after = reduced.locator("[data-echo-logo]").bounding_box()
        assert_neutral_particles(reduced)
        assert_hidden_reveal(reduced, timeout=500)
        assert all(abs(core_before[key] - core_after[key]) < 0.5 for key in core_before), (
            "Reduced-motion core moved in response to the pointer."
        )
        start_at = time.monotonic()
        enter(reduced)
        assert time.monotonic() - start_at < 1.0
        assert_brand(reduced, "#echo-sidebar-brand")
        reduced_context.close()

        motion_context, motion_page = new_page()
        opening(motion_page)
        expect(motion_page.get_by_role("button", name="开始对话", exact=True)).to_be_enabled()
        motion_page.mouse.move(1300, 760)
        motion_page.wait_for_timeout(250)
        assert eye_offset(motion_page)["x"] > 2
        assert_particle_reaction(motion_page)
        first_particle = particles(motion_page)[0]
        motion_page.mouse.move(first_particle["baseX"] - 45, first_particle["baseY"] - 28)
        motion_page.wait_for_function(f"() => ({PARTICLE_GEOMETRY})()[0].dx > 5")
        motion_page.wait_for_function(f"() => ({REVEAL_GEOMETRY})().live.opacity > 0.95")
        motion_page.emulate_media(reduced_motion="reduce")
        assert_neutral_eyes(motion_page)
        assert_neutral_particles(motion_page)
        assert_hidden_reveal(motion_page, timeout=500)
        motion_page.mouse.move(100, 100)
        motion_page.wait_for_timeout(250)
        assert_neutral_eyes(motion_page)
        assert_neutral_particles(motion_page)
        assert_hidden_reveal(motion_page, timeout=500)
        assert motion_page.locator(".welcome-pointer-glow").evaluate(
            "element => Number(getComputedStyle(element).opacity) === 0"
        )
        motion_context.close()

        preference_context, preference = new_page()
        opening(preference)
        save_brand(preference)
        expect(preference.get_by_role("button", name="开始对话", exact=True)).to_be_enabled(
            timeout=3000
        )
        preference.get_by_role("button", name="开始对话", exact=True).click()
        preference.emulate_media(reduced_motion="reduce")
        ready(preference, timeout=1200)
        assert_brand(preference, "#echo-sidebar-brand")
        preference_context.close()

        first_context.close()
        control_page.close()
        control.close()
        browser.close()
        assert not errors, "Browser errors: " + json.dumps(errors, ensure_ascii=False)
        print(
            "Opening regression passed: first visit, keyboard entry, removed decorations, "
            "brand continuity, suggestions, replay preservation, generation gate, "
            "particle avoidance, pointer parallax, gaze, blink, responsive layout, resize, "
            "masked background artwork, fading pointer trails, and reduced motion."
        )


if __name__ == "__main__":
    run()
