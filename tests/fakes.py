"""Offline stand-ins for the browser and model. Tests never call paid APIs."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from hyperagent.browser import ActionError, Observation
from hyperagent.llm import Decision, LLMConfig, LLMError

PAGE_TEXT = "Example shop\n[1]<input type=text value=\"\">Search</input>\n[2]<button>Place order</button>"


class FakeBrowser:
    def __init__(self, fail: set[str] | None = None):
        self.calls: list[tuple] = []
        self.events: list[str] = []
        self.fail = fail or set()
        self.page = SimpleNamespace(url="https://shop.test/")
        self.text = PAGE_TEXT

    async def observe(self, *, screenshot: bool = False) -> Observation:
        return Observation(
            url=self.page.url, title="Shop", text=self.text, truncated=False,
            elements={1: {"id": 1, "tag": "input", "label": "Search", "rect": {"x": 1, "y": 2, "w": 3, "h": 4}},
                      2: {"id": 2, "tag": "button", "label": "Place order", "rect": {"x": 5, "y": 6, "w": 7, "h": 8}}},
            scroll={"y": 0, "viewport": 800, "height": 800, "width": 1280},
            tabs=[{"index": 0, "title": "Shop", "url": self.page.url, "active": True}],
        )

    async def element_rect(self, element_id: int) -> dict[str, float]:
        return {"x": 10.0, "y": 20.0, "w": 30.0, "h": 40.0}

    async def _act(self, name: str, *args: Any) -> str:
        self.calls.append((name, *args))
        if name in self.fail:
            raise ActionError(f"{name} failed")
        return f"{name} ok"

    async def navigate(self, url: str) -> str:
        self.page.url = url
        return await self._act("navigate", url)

    async def click(self, element_id: int) -> str:
        return await self._act("click", element_id)

    async def type_text(self, element_id: int, text: str, press_enter: bool, *, secret_ok: bool = False) -> str:
        return await self._act("type_text", element_id, text, press_enter)

    async def select_option(self, element_id: int, option: str) -> str:
        return await self._act("select_option", element_id, option)

    async def scroll(self, direction: str, pages: float = 1) -> str:
        return await self._act("scroll", direction, pages)

    async def read_page(self) -> dict[str, Any]:
        self.calls.append(("read_page",))
        return {"text": "full text", "truncated": False, "length": 9}

    async def read_urls_parallel(self, urls: list[str]) -> dict[str, Any]:
        self.calls.append(("read_urls_parallel", *urls))
        pages = [{"url": u, "title": u, "text": f"text of {u}", "length": 0 if "broken" in u else 20,
                  "truncated": False} for u in urls]
        return {"text": "\n".join(p["text"] for p in pages), "length": 20 * len(urls), "truncated": False,
                "pages": pages}


def decision(name: str, **args: Any) -> Decision:
    reasoning = {"evaluation": "ok", "memory": "m", "next_goal": f"do {name}", "message": f"do {name}"}
    return Decision(name=name, args={**reasoning, **args}, input_tokens=10, output_tokens=5, cost_usd=0.001)


DONE = decision("done", success=True, summary="All set", columns=["a"], rows=[{"a": "1"}],
                sources=[{"title": "Shop", "url": "https://shop.test/"}], issues=[])


class ScriptedLLM:
    """Returns queued decisions; an item may be an Exception to raise or an asyncio.Event to wait on first."""

    def __init__(self, script: list[Any], key: str = "test-key"):
        self.script = list(script)
        self.config = LLMConfig(base_url="http://llm.test", api_key=key, models=("test-model",),
                                extract_model="test-extractor")
        self.requests: list[dict[str, Any]] = []
        self.json_replies: list[Any] = []  # queued extract answers; an Exception is raised instead
        self.json_requests: list[str] = []

    async def complete_json(self, system: str, user: str, *, max_tokens: int = 4000) -> tuple[dict, int, int, float]:
        self.json_requests.append(user)
        item = self.json_replies.pop(0) if self.json_replies else {"rows": []}
        if isinstance(item, Exception):
            raise item
        return item, 100, 20, 0.0001

    async def decide(self, model: str, messages: list, tools: list, *, force: str | None = None,
                     on_retry: Any = None, on_delta: Any = None, hard: bool = True) -> Decision:
        self.requests.append({"messages": messages, "force": force, "tools": tools, "hard": hard})
        if force == "done":
            return decision("done", success=True, summary="Partial summary", columns=[], rows=[], sources=[],
                            issues=["model issue"])
        if not self.script:
            raise LLMError("script exhausted")
        item = self.script.pop(0)
        if isinstance(item, asyncio.Event):
            await item.wait()
            item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Recorder:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == kind]

    def last_step(self, step_id: str) -> dict[str, Any]:
        return [e for e in self.of("step") if e["id"] == step_id][-1]
