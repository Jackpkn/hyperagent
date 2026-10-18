"""Session re-attach after a page reload, with a fake socket (no browser, no model)."""

import asyncio
from types import SimpleNamespace

from hyperagent import server
from hyperagent.server import DETACHED, Session, reattach


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, message):
        self.sent.append(message)


def make_session(ws=None):
    llm = SimpleNamespace(config=SimpleNamespace(default_model="m", models=["m"], api_key="k"))
    return Session(ws or FakeSocket(), llm, asyncio.Semaphore(2))


async def busy(session):
    session.task = asyncio.create_task(asyncio.sleep(30))
    return session.task


async def test_streaming_updates_of_one_step_collapse_but_order_is_kept():
    session = make_session()
    await session.send({"type": "step", "id": "s1", "status": "thinking"})
    await session.send({"type": "step", "id": "s1", "status": "planned"})
    await session.send({"type": "approval", "step_id": "s1"})
    await session.send({"type": "step", "id": "s1", "status": "done"})
    await session.send({"type": "frame", "data": "jpeg"})
    assert [(m["type"], m.get("status")) for m in session.backlog] == [
        ("step", "planned"), ("approval", None), ("step", "done")]
    assert session.last_frame == {"type": "frame", "data": "jpeg"}


async def test_reloaded_page_reattaches_to_the_running_session_and_gets_the_replay():
    old_socket, new_socket = FakeSocket(), FakeSocket()
    session = make_session(old_socket)
    task = await busy(session)
    await session.send({"type": "step", "id": "s1", "status": "done"})
    await session.send({"type": "frame", "data": "jpeg"})

    assert session.detach()
    assert DETACHED[session.resume_token] is session
    await session.send({"type": "step", "id": "s2", "status": "running"})  # while nobody is watching
    assert all(m.get("id") != "s2" for m in old_socket.sent)

    fresh = make_session(new_socket)
    attached = await reattach(fresh, new_socket, session.resume_token)

    assert attached is session and session.resume_token not in DETACHED
    kinds = [m["type"] for m in new_socket.sent]
    assert kinds == ["hello", "attached", "step", "step", "frame"]
    assert [m.get("id") for m in new_socket.sent if m["type"] == "step"] == ["s1", "s2"]
    await session.send({"type": "notice", "message": "live again"})
    assert new_socket.sent[-1]["message"] == "live again"
    task.cancel()


async def test_unknown_token_is_reported_and_the_fresh_session_stays():
    socket = FakeSocket()
    fresh = make_session(socket)
    assert await reattach(fresh, socket, "not-a-token") is fresh
    assert socket.sent[-1]["type"] == "attach_failed"


async def test_idle_session_is_closed_not_detached_and_detached_runs_expire(monkeypatch):
    idle = make_session()
    assert not idle.detach()

    session = make_session()
    task = await busy(session)
    monkeypatch.setitem(session.cfg, "detach_grace_seconds", 0)
    assert session.detach()
    await asyncio.sleep(0.05)
    assert session.resume_token not in DETACHED
    task.cancel()


def test_tokens_are_unguessable_and_distinct():
    a, b = make_session_sync(), make_session_sync()
    assert a.resume_token != b.resume_token and len(a.resume_token) >= 32
    assert a.session_id not in a.resume_token


def make_session_sync():
    llm = SimpleNamespace(config=SimpleNamespace(default_model="m", models=["m"], api_key="k"))
    return server.Session(FakeSocket(), llm, asyncio.Semaphore(1))
