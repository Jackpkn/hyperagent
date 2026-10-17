"""Real WebSocket protocol tests with browser/model boundaries replaced offline."""

import asyncio
import threading
from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from hyperagent import server


class FakeAgent:
    instances = []
    prediction_started = None
    release_prediction = None

    def __init__(self, url, goal, **_kwargs):
        self.state = {"goal": goal, "status": "ready", "history": [], "decisions": [],
                      "text_calls": [], "page": {"url": url, "fingerprint": "one", "text": "Search",
                                                 "actions": [], "screenshot": None}}
        self.closed = False
        self.closed_event = threading.Event()
        self.executions = 0
        self.goals = []
        self.instances.append(self)

    def snapshot(self):
        return deepcopy({**self.state, "elements": [], "last_page_changed": True})

    def predict(self, **_kwargs):
        self.goals.append(self.state["goal"])
        if self.prediction_started:
            self.prediction_started.set()
            assert self.release_prediction.wait(3)
        result = {"operation": "WAIT", "target": None, "target_label": "Wait",
                  "target_probabilities": {}, "goal_satisfied_noul": 0,
                  "irreversible_risk_noul": 0, "confidence": 1, "latency_ms": 5}
        self.state["decisions"].append(result)
        return result

    def execute_predicted(self, _pred, *, before_action=None):
        if before_action:
            before_action()
        self.executions += 1
        self.state["history"].append({"step": self.executions, "page_changed": True})

    def close(self):
        self.closed = True
        self.closed_event.set()

    def refresh(self):
        return self.snapshot()


@pytest.fixture
def client(monkeypatch):
    FakeAgent.instances = []
    FakeAgent.prediction_started = FakeAgent.release_prediction = None
    monkeypatch.setattr(server, "Agent", FakeAgent)
    with TestClient(server.app) as client:
        yield client


def receive(ws, kind):
    for _ in range(30):
        msg = ws.receive_json()
        if msg["type"] == "ERROR":
            pytest.fail(str(msg))
        if msg["type"] == kind:
            return msg
    pytest.fail(f"No {kind} event")


def start(ws, goal="Find a book", auto=False):
    ws.send_json({"command": "START", "url": "https://example.test", "goal": goal, "auto_run": auto})
    return receive(ws, "STATE_SNAPSHOT")


def test_sessions_are_independent_and_disconnect_closes_only_owner(client):
    with client.websocket_connect("/ws/agent") as first:
        start(first, "First task")
        with client.websocket_connect("/ws/agent") as second:
            start(second, "Second task")
            assert not FakeAgent.instances[0].closed
        assert not FakeAgent.instances[0].closed
    assert all(agent.closed_event.wait(2) for agent in FakeAgent.instances)


def test_pause_and_whisper_are_received_during_inference(client):
    FakeAgent.prediction_started = threading.Event()
    FakeAgent.release_prediction = threading.Event()
    try:
        with client.websocket_connect("/ws/agent") as ws:
            start(ws, auto=True)
            assert FakeAgent.prediction_started.wait(2)
            ws.send_json({"command": "PAUSE"})
            receive(ws, "PAUSE_REQUESTED")
            ws.send_json({"command": "WHISPER", "note": "Only hardcover"})
            receive(ws, "WHISPER_ACK")
            FakeAgent.release_prediction.set()
            receive(ws, "PAUSED")
            assert FakeAgent.instances[0].executions == 0
            ws.send_json({"command": "STEP"})
            receive(ws, "STATE_SNAPSHOT")
            assert FakeAgent.instances[0].executions == 1
            assert "Only hardcover" in FakeAgent.instances[0].goals[-1]
    finally:
        FakeAgent.release_prediction.set()


def test_step_honors_risk_verdict(client, monkeypatch):
    original = FakeAgent.predict

    def risky(self, **kwargs):
        return {**original(self, **kwargs), "irreversible_risk_noul": 0.99}

    monkeypatch.setattr(FakeAgent, "predict", risky)
    with client.websocket_connect("/ws/agent") as ws:
        start(ws)
        ws.send_json({"command": "STEP"})
        receive(ws, "HUMAN_APPROVAL_REQUIRED")
        assert FakeAgent.instances[0].executions == 0


def test_done_without_independent_verifier_is_unverified(client, monkeypatch):
    original = FakeAgent.predict

    def done(self, **kwargs):
        return {**original(self, **kwargs), "operation": "DONE"}

    monkeypatch.setattr(FakeAgent, "predict", done)
    with client.websocket_connect("/ws/agent") as ws:
        start(ws)
        ws.send_json({"command": "STEP"})
        result = receive(ws, "OUTCOME_UNVERIFIED")
        assert result["verification"]["satisfied"] is False
        assert FakeAgent.instances[0].executions == 0


def test_start_requires_explicit_goal_and_url(client):
    with client.websocket_connect("/ws/agent") as ws:
        ws.send_json({"command": "START"})
        assert ws.receive_json()["type"] == "ERROR"
        assert FakeAgent.instances == []


def test_completion_is_discarded_if_page_changes_during_verification(monkeypatch):
    async def verified(*_args, **_kwargs):
        return {"satisfied": True, "evidence_quotes": ["Search"]}

    async def extract(*_args, **_kwargs):
        return {"executive_summary": "Observed result", "structured_table": []}

    monkeypatch.setattr(server, "verify_outcome", verified)
    monkeypatch.setattr(server, "compile_final_deliverable", extract)

    async def scenario():
        session = server.AgentSession(Mock(send_json=AsyncMock()))
        session.agent = FakeAgent("https://example.test", "Find a report")
        session.context = {"normalized_goal": "Find a report"}
        snapshots = [session.agent.snapshot(), session.agent.snapshot()]
        snapshots[1]["page"]["fingerprint"] = "changed-during-verification"
        session.agent.refresh = Mock(side_effect=snapshots)
        try:
            await session.finish(verify=True)
            events = [call.args[0]["type"] for call in session.ws.send_json.call_args_list]
            assert "OUTCOME_UNVERIFIED" in events
            assert "MISSION_COMPLETE" not in events
        finally:
            session.executor.shutdown(wait=True)

    asyncio.run(scenario())


def test_auto_run_executes_multiple_steps_without_step_commands(client):
    with client.websocket_connect('/ws/agent') as ws:
        start(ws, auto=True)
        for _ in range(3):
            receive(ws, 'STATE_SNAPSHOT')
        ws.send_json({'command': 'PAUSE'})
        receive(ws, 'PAUSED')
        assert FakeAgent.instances[0].executions >= 3


def test_page_change_before_input_replans_without_manual_step(client, monkeypatch):
    from hyperagent.browser import BeforeActionStale

    original = FakeAgent.predict
    calls = []

    def changing(self, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise BeforeActionStale('Changed before choosing')
        return original(self, **kwargs)

    monkeypatch.setattr(FakeAgent, 'predict', changing)
    with client.websocket_connect('/ws/agent') as ws:
        start(ws, auto=True)
        receive(ws, 'ACTIVITY')
        while FakeAgent.instances[0].executions == 0:
            receive(ws, 'STATE_SNAPSHOT')
        ws.send_json({'command': 'PAUSE'})
        receive(ws, 'PAUSED')
        assert len(calls) >= 2


def test_stale_observation_after_execution_never_replays_action(client, monkeypatch):
    from hyperagent.browser import StalePage

    def executed(self, pred, **kwargs):
        self.executions += 1
        raise StalePage('Observation lost after execution')

    monkeypatch.setattr(FakeAgent, 'execute_predicted', executed)
    with client.websocket_connect('/ws/agent') as ws:
        start(ws, auto=True)
        msg = ws.receive_json()
        while msg['type'] != 'ERROR':
            msg = ws.receive_json()
        assert FakeAgent.instances[0].executions == 1
        assert receive(ws, 'STATE_SNAPSHOT')['status'] == 'paused'


def test_preview_queue_keeps_only_latest_frame():
    session = server.AgentSession(Mock(send_json=AsyncMock()))
    try:
        session.offer_frame({'screenshot': 'first'})
        session.offer_frame({'screenshot': 'latest'})
        assert session.frames.qsize() == 1
        assert session.frames.get_nowait()['screenshot'] == 'latest'
    finally:
        session.executor.shutdown(wait=True)


def test_second_stale_read_pauses_without_destroying_session(client, monkeypatch):
    from hyperagent.browser import BeforeActionStale, StalePage

    monkeypatch.setattr(FakeAgent, 'predict', Mock(side_effect=BeforeActionStale('Page changed')))
    monkeypatch.setattr(FakeAgent, 'refresh', Mock(side_effect=StalePage('Still navigating')))
    with client.websocket_connect('/ws/agent') as ws:
        start(ws, auto=True)
        receive(ws, 'PAUSED')
        assert not FakeAgent.instances[0].closed
        ws.send_json({'command': 'STOP'})
        receive(ws, 'STOPPED')


def test_blocked_policy_gets_recovery_before_stopping(client, monkeypatch):
    original = FakeAgent.predict

    def blocked(self, **kwargs):
        return {**original(self, **kwargs), 'operation': 'BLOCKED'}

    seen = []

    async def recovery(*args, **kwargs):
        seen.append(kwargs['page_text'])
        return {'action': 'OVERRIDE', 'operation': 'WAIT', 'target_id': None,
                'requires_approval': False, 'reasoning': 'Wait for the current page'}

    def override(self, operation, target, **kwargs):
        assert operation == 'WAIT'
        self.execute_predicted({}, **kwargs)

    monkeypatch.setattr(FakeAgent, 'predict', blocked)
    monkeypatch.setattr(FakeAgent, 'execute_override', override, raising=False)
    monkeypatch.setattr(server, 'resolve_system1_deadlock', recovery)
    with client.websocket_connect('/ws/agent') as ws:
        start(ws)
        ws.send_json({'command': 'STEP'})
        receive(ws, 'SYS2_RECOVERY_DECISION')
        receive(ws, 'STATE_SNAPSHOT')
        assert seen == ['Search']
        assert FakeAgent.instances[0].executions == 1


def test_invalid_policy_response_escalates_without_executing_it(client, monkeypatch):
    from hyperagent.model import InvalidPolicyResponse

    monkeypatch.setattr(FakeAgent, "predict", Mock(side_effect=InvalidPolicyResponse("Invalid choice")))
    recovery = AsyncMock(return_value={"action": "BLOCKED", "summary": "The page requires review."})
    monkeypatch.setattr(server, "resolve_system1_deadlock", recovery)
    with client.websocket_connect('/ws/agent') as ws:
        start(ws)
        ws.send_json({'command': 'STEP'})
        receive(ws, 'SYS2_RECOVERY_DECISION')
        receive(ws, 'PAUSED')
        assert FakeAgent.instances[0].executions == 0
        assert recovery.call_count == 1
