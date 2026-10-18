"""FastAPI service: one agent + one owned browser per WebSocket, plus the static console."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from collections import Counter
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .agent import SEARCH_URL, Agent
from .browser import ActionError, BrowserSession
from .fast import FastConfig, FastPolicy
from .llm import LLMClient, LLMConfig

log = logging.getLogger("hyperagent")
Mode = Literal["risky", "always", "never"]


class Command(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    type: Literal["start", "pause", "resume", "stop", "guide", "approve", "reject", "set_mode",
                  "takeover_click", "takeover_type", "takeover_scroll", "takeover_tab",
                  "save_session", "clear_session"]
    goal: str | None = Field(default=None, max_length=4000)
    start_url: str | None = Field(default=None, max_length=2000)
    approval_mode: Mode | None = None
    model: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)
    continue_session: bool = False
    persist_session: bool = False
    operator_context: str | None = Field(default=None, max_length=2000)
    text: str | None = Field(default=None, max_length=4000)
    step_id: str | None = Field(default=None, max_length=32)
    reason: str | None = Field(default=None, max_length=500)
    x: float | None = None
    y: float | None = None
    pin_x: float | None = None
    pin_y: float | None = None
    dy: float | None = None
    tab_index: int | None = None
    press_enter: bool = False


def settings() -> dict[str, Any]:
    return {
        "max_steps": int(os.environ.get("MAX_STEPS", "60")),
        "max_run_seconds": int(os.environ.get("MAX_RUN_SECONDS", "900")),
        "max_sessions": int(os.environ.get("MAX_SESSIONS", "3")),
        "start_url": os.environ.get("START_PAGE_URL", "https://www.bing.com/"),
        "search_url": os.environ.get("SEARCH_URL", SEARCH_URL),
        "vision": os.environ.get("AGENT_VISION", "1") != "0",
        "max_cost_usd": float(os.environ.get("MAX_RUN_COST_USD", "3.0")),
        "idle_close_seconds": int(os.environ.get("IDLE_CLOSE_SECONDS", "300")),
        "max_sockets_per_ip": int(os.environ.get("MAX_SOCKETS_PER_IP", "4")),
        "storage_state_path": Path(os.environ.get("STORAGE_STATE_PATH", ".hyperagent/storage_state.json")),
        "domain_memory_path": Path(os.environ.get("DOMAIN_MEMORY_PATH", ".hyperagent/domain_memory.json")),
        "runs_dir": Path(os.environ.get("RUNS_DIR", ".hyperagent/runs")),
    }


def _load_domain_memory(path: Path) -> dict[str, list[str]]:
    with contextlib.suppress(OSError, ValueError):
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return {str(k): [str(x) for x in v if str(x)][:5] for k, v in raw.items() if isinstance(v, list)}
    return {}


def _save_domain_memory(path: Path, updates: dict[str, list[str]]) -> None:
    if not updates:
        return
    with contextlib.suppress(OSError):
        current = _load_domain_memory(path)
        for domain, notes in updates.items():
            existing = current.get(domain, [])
            merged = list(dict.fromkeys([*notes, *existing]))[:5]
            current[domain] = merged
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")


class Session:
    def __init__(self, ws: WebSocket, llm: LLMClient, slots: asyncio.Semaphore, fast: FastPolicy | None = None):
        self.ws, self.llm, self.slots, self.fast = ws, llm, slots, fast
        self.cfg = settings()
        self.session_id = hex(id(self))[2:]
        self.browser: BrowserSession | None = None
        self.agent: Agent | None = None
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.closed = False
        self.holding_slot = False
        self.persist_session = False
        self.idle_timer: asyncio.TimerHandle | None = None

    def _append_journal(self, message: dict[str, Any]) -> None:
        if message.get("type") == "frame":
            return
        with contextlib.suppress(OSError):
            runs_dir: Path = self.cfg["runs_dir"]
            runs_dir.mkdir(parents=True, exist_ok=True)
            journal = runs_dir / f"{self.session_id}.jsonl"
            with journal.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(message, ensure_ascii=False) + "\n")

    async def send(self, message: dict[str, Any]) -> None:
        self._append_journal(message)
        if self.closed:
            return
        async with self.lock:
            try:
                # A stalled client must not stall the agent; drop it instead.
                await asyncio.wait_for(self.ws.send_json(message), timeout=10)
            except (RuntimeError, WebSocketDisconnect, TimeoutError):
                self.closed = True
                if self.agent:
                    self.agent.detached = True

    async def _emit_hello(self) -> None:
        state_path: Path = self.cfg["storage_state_path"]
        await self.send({"type": "hello", "session_id": self.session_id, "model": self.llm.config.default_model,
                         "models": list(self.llm.config.models), "max_steps": self.cfg["max_steps"],
                         "configured": bool(self.llm.config.api_key),
                         "fast_model": self.fast.config.model if self.fast else None,
                         "has_saved_session": state_path.is_file()})

    async def hello(self) -> None:
        await self._emit_hello()
        await self.send({"type": "status", "state": "idle", "step": 0})

    async def error(self, message: str) -> None:
        await self.send({"type": "notice", "level": "error", "message": message})

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    async def handle(self, raw: Any) -> None:
        try:
            cmd = Command.model_validate(raw)
        except ValidationError:
            await self.error("That command was not understood.")
            return
        if cmd.type == "start":
            await self.start(cmd)
            return
        if cmd.type == "save_session":
            await self.save_session()
            return
        if cmd.type == "clear_session":
            await self.clear_session()
            return
        if cmd.type in ("takeover_click", "takeover_type", "takeover_scroll", "takeover_tab"):
            await self.takeover(cmd)
            return
        agent = self.agent
        if agent is None:
            await self.error("Start a task first.")
            return
        match cmd.type:
            case "pause":
                await agent.pause()
            case "resume":
                await agent.resume()
            case "stop":
                await agent.stop()
            case "guide":
                if not cmd.text:
                    await self.error("Type a message for the agent first.")
                elif not self.running:
                    await self.error("The task has finished. Start a new task to continue.")
                else:
                    text = cmd.text
                    if cmd.pin_x is not None and cmd.pin_y is not None and self.browser is not None:
                        desc = await self.browser.describe_point(cmd.pin_x, cmd.pin_y)
                        text = f"[Operator pinned target on page: {desc}] {text}"
                    await agent.guide(text)
            case "approve" | "reject":
                if not agent.resolve_approval(cmd.step_id or "", cmd.type == "approve", cmd.reason or ""):
                    await self.error("That step is no longer waiting for approval.")
            case "set_mode":
                if cmd.approval_mode:
                    agent.approval_mode = cmd.approval_mode
                    names = {"risky": "ask before risky actions", "always": "ask before every action",
                             "never": "fully autonomous"}
                    await agent.notice("info", f"Approval mode: {names[cmd.approval_mode]}.")

    async def save_session(self) -> None:
        if not self.browser or not self.browser.context:
            await self.error("No active browser session to save.")
            return
        ok = await self.browser.save_storage_state(self.cfg["storage_state_path"])
        if ok:
            await self._emit_hello()
            await self.send({"type": "notice", "level": "info",
                             "message": "Saved browser cookies and login session for future runs."})
        else:
            await self.error("Could not save the browser session.")

    async def clear_session(self) -> None:
        state_path: Path = self.cfg["storage_state_path"]
        with contextlib.suppress(OSError):
            if state_path.is_file():
                state_path.unlink()
        await self._emit_hello()
        await self.send({"type": "notice", "level": "info", "message": "Cleared saved browser session."})

    async def takeover(self, cmd: Command) -> None:
        agent, browser = self.agent, self.browser
        # Allowed when paused, waiting for user input, or after the run has finished while the browser stays open.
        if browser is None or (self.running and agent is not None and agent.state not in ("paused", "awaiting_user")):
            await self.error("Pause the agent before taking over the browser.")
            return
        try:
            if cmd.type == "takeover_click" and cmd.x is not None and cmd.y is not None:
                description = await browser.human_click(cmd.x, cmd.y)
            elif cmd.type == "takeover_type" and cmd.text:
                description = await browser.human_type(cmd.text, cmd.press_enter)
            elif cmd.type == "takeover_scroll" and cmd.dy is not None:
                description = await browser.human_scroll(cmd.dy)
            elif cmd.type == "takeover_tab" and cmd.tab_index is not None:
                description = await browser.switch_tab(cmd.tab_index)
            else:
                await self.error("Incomplete takeover command.")
                return
        except ActionError as exc:
            await self.error(str(exc))
            return
        except Exception:  # noqa: BLE001 - a failed manual action must not end the session
            log.exception("takeover failed")
            await self.error("That browser action did not work. Try again or resume the agent.")
            return
        if agent is not None and self.running:
            await agent.operator_action(description)
        if self.persist_session and cmd.type in ("takeover_click", "takeover_type"):
            await browser.save_storage_state(self.cfg["storage_state_path"])
            await self._emit_hello()
        await browser.send_frame()

    async def start(self, cmd: Command) -> None:
        if self.running:
            await self.error("A task is already running. Stop it before starting another.")
            return
        if not cmd.goal:
            await self.error("Describe what you want the agent to do.")
            return
        model = cmd.model if cmd.model in self.llm.config.models else self.llm.config.default_model
        start_url = cmd.start_url or ""
        if start_url and "://" not in start_url:
            start_url = "https://" + start_url
        if start_url and not start_url.startswith(("http://", "https://")):
            await self.error("The start URL must be an http(s) web address.")
            return
        if self.idle_timer:
            self.idle_timer.cancel()
            self.idle_timer = None
        if not self.holding_slot:
            if self.slots.locked():
                await self.error("All browser slots are busy right now. Please try again in a minute.")
                return
            await self.slots.acquire()
            self.holding_slot = True
        self.persist_session = bool(cmd.persist_session)
        reuse_browser = bool(
            cmd.continue_session
            and self.browser is not None
            and self.browser.context is not None
            and self.browser._tabs_list()
        )
        prev_findings = list(self.agent.findings) if (reuse_browser and self.agent) else []
        if not reuse_browser:
            await self.close_browser()
            await self.send({"type": "status", "state": "starting", "step": 0, "detail": "Opening a fresh browser…"})
            self.browser = BrowserSession(on_frame=self.on_frame)
        else:
            await self.send({"type": "status", "state": "starting", "step": 0,
                             "detail": "Continuing on the current browser page…"})
        domain_mem = _load_domain_memory(self.cfg["domain_memory_path"])
        self.agent = Agent(
            browser=self.browser, llm=self.llm, emit=self.send, goal=cmd.goal, model=model,
            approval_mode=cmd.approval_mode or "risky", max_steps=self.cfg["max_steps"],
            vision=self.cfg["vision"], search_url=self.cfg["search_url"], max_cost_usd=self.cfg["max_cost_usd"],
            fast=self.fast, timezone=cmd.timezone, domain_memory=domain_mem,
        )
        if prev_findings:
            self.agent.findings = prev_findings
            await self.send({"type": "findings", "items": self.agent.findings})
        if cmd.operator_context:
            self.agent.guidance.append(
                f"Operator autofill/context profile (use when filling matching fields): {cmd.operator_context}"
            )
        self.task = asyncio.create_task(
            self.run(self.agent, self.browser, start_url, reuse_browser=reuse_browser)
        )

    async def run(self, agent: Agent, browser: BrowserSession, url: str, *, reuse_browser: bool = False) -> None:
        if not reuse_browser:
            try:
                storage = self.cfg["storage_state_path"] if self.persist_session else None
                # The operator's URL is untrusted (http(s) only); the configured default page is trusted.
                await browser.start(url or self.cfg["start_url"], trusted=not url, storage_state=storage)
            except ActionError as exc:
                await self.error(str(exc))
                await self.send({"type": "status", "state": "failed", "step": 0, "detail": str(exc)})
                self.schedule_idle_close()
                return
        elif url:
            try:
                await browser.navigate(url, trusted=False)
            except ActionError as exc:
                await self.error(str(exc))
        timer = asyncio.get_running_loop().call_later(self.cfg["max_run_seconds"],
                                                      lambda: asyncio.ensure_future(self._timeout(agent)))
        try:
            result = await agent.run()
            state = "stopped" if agent.stopped else "done" if result.get("success") else "failed"
            issues = result.get("issues") or []
            detail = "" if result.get("success") or not issues else str(issues[0])[:140]
            await agent.set_state(state, detail)
        except Exception:  # noqa: BLE001 - never leave the operator without a terminal state
            log.exception("agent run crashed")
            await self.error("The agent hit an internal error and stopped. Everything it found is shown above.")
            await self.send({"type": "status", "state": "failed", "step": agent.actions_taken})
        finally:
            timer.cancel()
            _save_domain_memory(self.cfg["domain_memory_path"], agent.distill_domain_notes())
            if self.persist_session and browser.context:
                if await browser.save_storage_state(self.cfg["storage_state_path"]):
                    await self._emit_hello()
            self.schedule_idle_close()

    def schedule_idle_close(self) -> None:
        """Keep the final page visible for a while, then free the browser slot for other people."""
        if self.idle_timer:
            self.idle_timer.cancel()
        self.idle_timer = asyncio.get_running_loop().call_later(
            self.cfg["idle_close_seconds"], lambda: asyncio.ensure_future(self.release()))

    async def release(self) -> None:
        if self.running:
            return
        try:
            await self.close_browser()
        finally:
            if self.holding_slot:
                self.slots.release()
                self.holding_slot = False

    async def _timeout(self, agent: Agent) -> None:
        await agent.stop()
        await agent.notice("warn", f"Time limit of {self.cfg['max_run_seconds'] // 60} minutes reached; wrapping up.")

    async def on_frame(self, frame: dict[str, Any]) -> None:
        await self.send({"type": "frame", **frame})

    async def close_browser(self) -> None:
        if self.browser:
            await self.browser.close()
            self.browser = None

    async def close(self) -> None:
        self.closed = True
        if self.idle_timer:
            self.idle_timer.cancel()
        if self.agent:
            self.agent.detached = True
            await self.agent.stop()
        if self.task:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.task, timeout=15)
        try:
            await self.close_browser()
        finally:
            if self.holding_slot:
                self.slots.release()
                self.holding_slot = False


LLM = LLMClient(LLMConfig.from_env())
FAST_CONFIG = FastConfig.from_env()
FAST = FastPolicy(FAST_CONFIG) if FAST_CONFIG.enabled else None
SLOTS = asyncio.Semaphore(settings()["max_sessions"])
SOCKETS_PER_IP: Counter[str] = Counter()


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await LLM.close()
    if FAST:
        await FAST.close()


app = FastAPI(title="HyperAgent", version="0.2.0", lifespan=lifespan)


@app.get("/api/health")
@app.get("/healthz")
async def health() -> dict[str, Any]:
    return {"status": "ok", "model_configured": bool(LLM.config.api_key), "fast_configured": FAST is not None}


def origin_allowed(origin: str | None, host: str | None) -> bool:
    """Same-origin consoles and local development are allowed; other origins must be listed."""
    if origin is None:
        return True
    allowed = {o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()}
    same_origin = host is not None and origin.split("://", 1)[-1] == host
    local = origin.startswith(("http://localhost:", "http://127.0.0.1:"))
    return same_origin or local or "*" in allowed or origin in allowed


@app.websocket("/ws/agent")
async def agent_socket(ws: WebSocket) -> None:
    if not origin_allowed(ws.headers.get("origin"), ws.headers.get("host")):
        await ws.close(code=1008)
        return
    ip = ws.headers.get("x-forwarded-for", "").split(",")[0].strip() or (ws.client.host if ws.client else "?")
    if SOCKETS_PER_IP[ip] >= settings()["max_sockets_per_ip"]:
        await ws.close(code=1013)
        return
    await ws.accept()
    SOCKETS_PER_IP[ip] += 1
    session = Session(ws, LLM, SLOTS, FAST)
    await session.hello()
    try:
        while True:
            try:
                raw = await ws.receive_json()
            except ValueError:
                await session.error("Send JSON commands.")
                continue
            await session.handle(raw)
    except WebSocketDisconnect:
        pass
    finally:
        SOCKETS_PER_IP[ip] -= 1
        await session.close()


web_dist = Path(os.environ.get("WEB_DIST", "apps/web/out"))
if web_dist.is_dir():
    app.mount("/", StaticFiles(directory=web_dist, html=True), name="console")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8766")),
                ws_max_size=2**20)


if __name__ == "__main__":
    main()
