"""Console design interactions against the static export, real IndexedDB and local socket data."""

import base64
import json
import os
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

from tests.test_chat_refresh import RESULT, WEB, QuietHandler, wait_saved


@pytest.fixture
async def design_console():
    if not (WEB / "out" / "index.html").exists():
        pytest.skip("Build apps/web before running console design tests")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(WEB / "out")))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page(viewport={"width": 1440, "height": 1050},
                                              color_scheme="dark", timezone_id="UTC")
                page.set_default_timeout(5000)
                await page.route("https://fonts.googleapis.com/**", lambda route: route.fulfill(body=""))
                sockets, messages = [], []

                def connect(ws):
                    sockets.append(ws)
                    ws.on_message(lambda message: messages.append(json.loads(message)))
                    ws.send(json.dumps({"type": "hello", "session_id": "design-test", "model": "offline",
                                        "models": ["offline", "offline-alternate"], "max_steps": 60,
                                        "configured": True}))
                    ws.send(json.dumps({"type": "status", "state": "idle", "step": 0}))

                await page.route_web_socket("**/ws/agent", connect)
                await page.goto(f"http://127.0.0.1:{server.server_port}")
                await expect(page.get_by_text("Connected", exact=True)).to_be_visible()
                yield page, sockets, messages
            finally:
                await browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


async def start_task(page, goal="Compare the catalog items"):
    await page.get_by_role("textbox", name="Your goal").fill(goal)
    await page.get_by_role("button", name="Start agent", exact=True).click()


async def screenshot(page, name):
    if directory := os.environ.get("CONSOLE_SCREENSHOTS"):
        await page.screenshot(path=str(Path(directory) / f"{name}.png"), full_page=True, animations="disabled")


async def test_examples_are_editable_and_share_composer_edges(design_console):
    page, _, messages = design_console
    cards = page.get_by_role("button", name="Use example:")
    await expect(cards).to_have_count(4)
    composer = await page.locator(".goal-box").bounding_box()
    grid = await page.locator(".starter-grid").bounding_box()
    assert abs(composer["x"] - grid["x"]) < 1
    assert abs(composer["width"] - grid["width"]) < 1
    assert 880 <= composer["width"] <= 1000
    card_boxes = [await card.bounding_box() for card in await cards.all()]
    assert card_boxes[0]["y"] == card_boxes[1]["y"] < card_boxes[2]["y"]
    await screenshot(page, "launcher-desktop-dark")
    await page.emulate_media(color_scheme="light")
    await screenshot(page, "launcher-desktop-light")
    await page.emulate_media(color_scheme="dark")
    for card in await cards.all():
        prompt = await card.locator(".starter-card-desc").inner_text()
        await card.click()
        await expect(page.get_by_role("textbox", name="Your goal")).to_have_value(prompt)
        await expect(page.get_by_role("textbox", name="Your goal")).to_be_focused()
    assert not any(message["type"] == "start" for message in messages)
    await page.get_by_role("textbox", name="Your goal").fill("My own editable goal")
    await page.get_by_role("button", name="Start agent", exact=True).click()
    assert next(message for message in messages if message["type"] == "start")["goal"] == "My own editable goal"


async def test_settings_disclosure_validates_hidden_url_and_preserves_start_payload(design_console):
    page, _, messages = design_console
    settings = page.get_by_role("button", name="Browser settings")
    await settings.click()
    url = page.get_by_role("textbox", name="Start at a URL (optional)")
    await url.fill("not-a-url")
    await url.press("Escape")
    await expect(settings).to_be_focused()
    await expect(url).to_be_hidden()
    await page.get_by_role("textbox", name="Your goal").fill("Inspect this catalog")
    await page.get_by_role("button", name="Start agent", exact=True).click()
    await expect(url).to_be_visible()
    await expect(url).to_be_focused()
    assert not any(message["type"] == "start" for message in messages)
    await url.fill("https://example.com/catalog")
    await page.get_by_role("switch", name="Keep logins").click()
    await page.get_by_role("radio", name="Ask before every action").check()
    await url.press("Escape")
    await page.get_by_role("combobox", name="Planner model (System 2)").select_option("offline-alternate")
    await page.get_by_role("textbox", name="Your goal").press("Control+Enter")
    await expect(page.get_by_role("button", name="Pause", exact=True)).to_be_visible()
    assert next(message for message in messages if message["type"] == "start") == {
        "type": "start", "goal": "Inspect this catalog", "start_url": "https://example.com/catalog",
        "approval_mode": "always", "model": "offline-alternate", "persist_session": True, "timezone": "UTC",
    }


async def test_sidebar_opens_saved_chat_new_task_and_delete(design_console):
    page, sockets, _ = design_console
    await expect(page.get_by_role("button", name="Collapse chat sidebar")).to_be_visible()
    await page.get_by_role("button", name="Autofill profile", exact=True).click()
    await expect(page.get_by_role("dialog")).to_be_visible()
    await page.get_by_role("button", name="Close modal", exact=True).click()
    await page.get_by_role("button", name="Memory", exact=True).click()
    await expect(page.get_by_role("dialog", name="Memory (0)", exact=True)).to_be_visible()
    await page.get_by_role("button", name="Close", exact=True).click()
    await start_task(page)
    sockets[-1].send(json.dumps(RESULT))
    sockets[-1].send(json.dumps({"type": "status", "state": "done", "step": 0}))
    await wait_saved(page, lambda turn: turn and turn["result"] is not None)
    await page.get_by_role("button", name="New task", exact=True).click()
    await expect(page.get_by_role("textbox", name="Your goal")).to_be_visible()
    chat = page.get_by_role("navigation", name="Chats").get_by_role(
        "button", name="Compare the catalog items", exact=True)
    await chat.click()
    await expect(page.get_by_text("Catalog comparison complete.", exact=True)).to_be_visible()
    await expect(chat).to_have_attribute("aria-current", "page")
    assert page.url.endswith("/")
    await page.reload()
    await expect(page.get_by_text("Catalog comparison complete.", exact=True)).to_be_visible()
    await page.get_by_role("button", name="Collapse chat sidebar").click()
    await expect(chat).to_be_hidden()
    await page.get_by_role("button", name="Expand chat sidebar").click()
    await page.get_by_role("button", name="New task", exact=True).click()
    await page.get_by_role("button", name="Delete chat: Compare the catalog items", exact=True).click()
    await expect(chat).to_have_count(0)
    await wait_saved(page, lambda turn: turn is None)
    await page.reload()
    await expect(chat).to_have_count(0)


async def test_sidebar_switch_preserves_stop_before_opening_a_saved_chat(design_console):
    page, sockets, messages = design_console
    await start_task(page, "Saved catalog comparison")
    sockets[-1].send(json.dumps(RESULT))
    sockets[-1].send(json.dumps({"type": "status", "state": "done", "step": 0}))
    await wait_saved(page, lambda turn: turn and turn["result"] is not None)
    await page.get_by_role("button", name="New task", exact=True).click()
    await start_task(page, "A second task")
    sockets[-1].send(json.dumps({"type": "status", "state": "running", "step": 1}))
    await expect(page.get_by_role("button", name="Delete chat: A second task", exact=True)).to_be_disabled()
    before = len(messages)
    await page.get_by_role("navigation", name="Chats").get_by_role(
        "button", name="Saved catalog comparison", exact=True).click()
    await expect(page.get_by_text("Catalog comparison complete.", exact=True)).to_be_visible()
    assert messages[before:] == [{"type": "stop"}]
    assert page.url.endswith("/")


@pytest.mark.parametrize("mobile", [False, True], ids=["desktop", "mobile"])
async def test_controls_stay_in_one_scrollable_row_and_keep_semantics(design_console, mobile):
    page, sockets, messages = design_console
    if mobile:
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.get_by_role("button", name="Collapse chat sidebar").click()
        cards = page.get_by_role("button", name="Use example:")
        await expect(cards).to_have_count(4)
        boxes = [await card.bounding_box() for card in await cards.all()]
        assert all(box["x"] == boxes[0]["x"] for box in boxes)
        await screenshot(page, "launcher-mobile-dark")
    await start_task(page)
    ws = sockets[-1]
    ws.send(json.dumps({"type": "status", "state": "running", "step": 3}))
    ws.send(json.dumps({"type": "usage", "input_tokens": 1234, "output_tokens": 321, "cost_usd": 0.012,
                        "elapsed_s": 42, "fast_calls": 3, "fast_ms_total": 900}))
    image = base64.b64encode((WEB / "scripts/mock-frames/frame-1.jpg").read_bytes()).decode()
    ws.send(json.dumps({"type": "frame", "image": image, "url": "https://example.com/catalog",
                        "title": "Catalog", "w": 1280, "h": 800, "tabs": []}))
    ws.send(json.dumps({"type": "findings", "items": [
        {"source_url": "https://example.com/catalog", "data": {"Item": "Comparison item", "Price": "$25"}},
    ]}))
    await expect(page.get_by_text("Comparison item", exact=True)).to_be_visible()
    controls = [page.locator(".brand-btn"), page.locator(".run-status-pill"), page.locator(".goal-pill"),
                page.get_by_label("Run metrics"), page.get_by_role("combobox", name="Approval mode"),
                page.get_by_role("button", name="Pause", exact=True),
                page.get_by_role("button", name="Stop", exact=True),
                page.locator(".conn-indicator")]
    boxes = [await control.bounding_box() for control in controls]
    centers = [box["y"] + box["height"] / 2 for box in boxes]
    assert max(centers) - min(centers) < 3, "Run controls wrapped into multiple rows"
    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    await screenshot(page, f"workspace-{'mobile' if mobile else 'desktop'}-dark")
    if not mobile:
        await page.emulate_media(color_scheme="light")
        await screenshot(page, "workspace-desktop-light")
        await page.emulate_media(color_scheme="dark")
    await page.get_by_role("button", name="Pause", exact=True).click()
    assert messages[-1] == {"type": "pause"}
    ws.send(json.dumps({"type": "status", "state": "paused", "step": 3}))
    await page.get_by_role("button", name="Resume", exact=True).click()
    assert messages[-1] == {"type": "resume"}
    await page.get_by_role("combobox", name="Approval mode").select_option("always")
    assert messages[-1] == {"type": "set_mode", "approval_mode": "always"}
    if mobile:
        await screenshot(page, "workspace-mobile-controls-dark")
    await page.get_by_role("button", name="Stop", exact=True).click()
    assert not any(message["type"] == "stop" for message in messages)
    await page.get_by_role("button", name="Confirm stop", exact=True).click()
    assert messages[-1] == {"type": "stop"}
