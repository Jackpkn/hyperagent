"""Real console + IndexedDB refresh checks; the socket is local fixture data, never a paid model.

Build apps/web first. These tests serve its static export in an isolated browser profile.
"""

import asyncio
import base64
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

WEB = Path(__file__).resolve().parents[1] / "apps" / "web"
FINDING = {"source_url": "https://example.com/catalog", "data": {"Item": "Refresh test item", "Price": "$25"}}
RESULT = {
    "type": "result", "success": True, "summary": "Catalog comparison complete.",
    "columns": ["Item", "Price"], "rows": [
        {"Item": "Refresh test item", "Price": "$25"}, {"Item": "Second item", "Price": "$30"},
    ],
    "sources": [{"title": "Catalog", "url": "https://example.com/catalog"}], "issues": [],
}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


@pytest.fixture
async def console():
    if not (WEB / "out" / "index.html").exists():
        pytest.skip("Build apps/web before running console refresh tests")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(WEB / "out")))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page()
                sockets = []

                def connect(ws):
                    sockets.append(ws)
                    ws.send(json.dumps({"type": "hello", "session_id": "refresh-test", "model": "offline",
                                        "models": ["offline"], "max_steps": 60, "configured": True}))
                    ws.send(json.dumps({"type": "status", "state": "idle", "step": 0}))
                    ws.on_message(lambda _: None)

                await page.route_web_socket("**/ws/agent", connect)
                await page.goto(f"http://127.0.0.1:{server.server_port}")
                await page.get_by_role("textbox").first.fill("Compare the catalog items")
                await page.get_by_role("button", name="Start agent", exact=True).click()
                yield page, sockets
            finally:
                await browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


async def saved_turn(page):
    return await page.evaluate("""() => new Promise((resolve, reject) => {
      const request = indexedDB.open('hyperagent', 1);
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const db = request.result;
        const tx = db.transaction('chats');
        const rows = tx.objectStore('chats').getAll();
        tx.oncomplete = () => { resolve(rows.result[0]?.turns.at(-1) ?? null); db.close(); };
      };
    })""")


async def wait_saved(page, predicate):
    for _ in range(30):
        turn = await saved_turn(page)
        if predicate(turn):
            return turn
        await asyncio.sleep(0.1)
    assert predicate(turn), "The latest turn was not persisted while browser frames continued arriving"


async def test_refresh_keeps_partial_findings_in_main_stream(console):
    page, sockets = console
    sockets[-1].send(json.dumps({"type": "findings", "items": [FINDING]}))
    sockets[-1].send(json.dumps({"type": "status", "state": "stopped", "step": 0}))
    await expect(page.get_by_text("Refresh test item", exact=True)).to_be_visible()
    await wait_saved(page, lambda turn: turn and len(turn["findings"]) == 1)
    await page.reload()
    await expect(page.get_by_text("Refresh test item", exact=True)).to_be_visible()
    await page.get_by_role("tab", name="Findings").click()
    await expect(page.get_by_text("Refresh test item", exact=True)).to_be_visible()


async def test_accounting_survives_refresh_without_savings_claims(console):
    from hyperagent.telemetry import CallRecord, RunLedger

    ledger = RunLedger()
    for purpose, cost in (("planner", 0.25), ("jev", None), ("text", 0.01)):
        ledger.record(CallRecord(run_id=ledger.run_id, purpose=purpose, step_id="s1", parent_step_id=None,
                                 logical_call_id=purpose, attempt_id=purpose, attempt=1,
                                 provider="typesafe" if purpose == "jev" else "openrouter", requested_model="test",
                                 input_tokens=100, output_tokens=10, cost_usd=cost,
                                 cost_basis="unknown" if cost is None else "provider"))
    page, sockets = console
    ws = sockets[-1]
    accounting = ledger.snapshot()
    usage = {"type": "usage", "llm_calls": 1, "input_tokens": 100, "output_tokens": 10,
             "cost_usd": 0.25, "elapsed_s": 1, "fast_calls": 1, "fast_ms_total": 100,
             "text_calls": 1, "accounting": ledger.snapshot(details=False)}
    ws.send(json.dumps(usage))
    ws.send(json.dumps({**RESULT, "accounting": accounting}))
    ws.send(json.dumps({"type": "status", "state": "done", "step": 2}))
    await expect(page.get_by_text("Catalog comparison complete.", exact=True)).to_be_visible()
    turn = await wait_saved(page, lambda turn: turn and turn["result"] is not None)
    assert turn["usage"].get("accounting") == usage["accounting"]
    assert turn["result"].get("accounting") == accounting
    await page.reload()
    await expect(page.locator('.telemetry-chip[title^="Known cost"]')).to_contain_text("$0.26")
    await expect(page.locator(".efficiency-strip")).to_contain_text("1 call")
    assert "tokens saved" not in await page.locator("body").inner_text()
    assert (await saved_turn(page))["result"]["accounting"] == accounting


async def test_refresh_flushes_latest_running_update(console):
    page, sockets = console
    ws = sockets[-1]
    ws.send(json.dumps({"type": "status", "state": "running", "step": 0}))
    ws.send(json.dumps({"type": "findings", "items": [FINDING]}))
    await wait_saved(page, lambda turn: turn and len(turn["findings"]) == 1)
    latest = {"source_url": "https://example.com/catalog", "data": {"Item": "Latest unsaved item"}}
    ws.send(json.dumps({"type": "findings", "items": [FINDING, latest]}))
    await expect(page.get_by_text("Latest unsaved item", exact=True)).to_be_visible()
    # Reload as soon as the new finding renders, without waiting for the periodic save.
    await page.reload()
    await expect(page.get_by_text("Latest unsaved item", exact=True)).to_be_visible()


@pytest.mark.parametrize("complete", [False, True], ids=["running-findings", "completed-report"])
async def test_frames_cannot_starve_chat_saves(console, complete):
    page, sockets = console
    ws = sockets[-1]
    image = base64.b64encode((WEB / "scripts/mock-frames/frame-1.jpg").read_bytes()).decode()
    frame = json.dumps({"type": "frame", "image": image, "url": "https://example.com/catalog",
                        "title": "Catalog", "w": 1280, "h": 800, "tabs": []})

    async def stream():
        while True:
            ws.send(frame)
            await asyncio.sleep(0.1)

    task = asyncio.create_task(stream())
    try:
        ws.send(json.dumps({"type": "status", "state": "running", "step": 0}))
        ws.send(json.dumps({"type": "findings", "items": [FINDING]}))
        if complete:
            ws.send(json.dumps(RESULT))
            ws.send(json.dumps({"type": "status", "state": "done", "step": 0}))
        await wait_saved(page, lambda turn: turn and (
            turn["result"] is not None if complete else len(turn["findings"]) == 1))
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    await page.reload()
    await expect(page.get_by_text("Refresh test item", exact=True)).to_be_visible()
    if complete:
        await expect(page.get_by_text("Catalog comparison complete.", exact=True)).to_be_visible()
        await page.get_by_role("tab", name="Report Only").click()
        await expect(page.get_by_role("cell", name="Refresh test item", exact=True)).to_be_visible()
