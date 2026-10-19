"""Session lifecycle checks with no browser process or model API calls."""

import asyncio
from types import SimpleNamespace

import pytest

from hyperagent.server import Command, Session


class Browser:
    def __init__(self):
        self.calls = []

    async def close(self):
        self.calls.append("close")

    async def human_scroll(self, dy):
        self.calls.append(("scroll", dy))
        return "Scrolled"

    async def send_frame(self):
        self.calls.append("frame")


@pytest.fixture
def session(tmp_path):
    messages = []

    async def send_json(message):
        messages.append(message)

    value = Session(SimpleNamespace(send_json=send_json), None, asyncio.Semaphore(1))
    value.cfg["runs_dir"] = tmp_path
    return value, messages


async def test_closing_browser_announces_read_only_view(session):
    value, messages = session
    browser = Browser()
    value.browser = browser
    await value.close_browser()
    assert value.browser is None
    assert browser.calls == ["close"]
    assert messages == [{"type": "browser_session", "active": False}]


async def test_expired_browser_does_not_ask_user_to_pause(session):
    value, messages = session
    await value.takeover(Command(type="takeover_scroll", dy=100))
    assert {"type": "browser_session", "active": False} in messages
    assert "closed" in messages[-1]["message"]
    assert not any("Pause" in message.get("message", "") for message in messages)


@pytest.mark.parametrize("state,allowed", [("thinking", False), ("acting", False),
                                         ("awaiting_approval", False), ("paused", True),
                                         ("awaiting_user", True), ("done", True)])
async def test_takeover_respects_agent_state_during_task_cleanup(session, state, allowed):
    value, messages = session
    browser = Browser()
    value.browser = browser
    notes = []

    async def operator_action(description):
        notes.append(description)

    value.agent = SimpleNamespace(state=state, operator_action=operator_action)
    value.task = asyncio.get_running_loop().create_future()
    try:
        await value.takeover(Command(type="takeover_scroll", dy=100))
        assert (("scroll", 100) in browser.calls) is allowed
        if not allowed:
            assert messages[-1]["message"] == "Pause the agent before taking over the browser."
    finally:
        value.task.cancel()
