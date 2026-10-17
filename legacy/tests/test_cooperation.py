"""Offline tests for cross-page evidence and one-shot operator approval."""

import json
from unittest.mock import AsyncMock, Mock

import pytest

from hyperagent import claude_sys2, server
from tests.test_server import FakeAgent


@pytest.mark.anyio
async def test_approval_is_bound_to_revision_and_consumed_once():
    session = server.AgentSession(Mock(send_json=AsyncMock()))
    session.agent = FakeAgent("https://example.test", "Submit the form")
    session.context = {"normalized_goal": "Submit the form"}
    pred = {"operation": "CLICK", "target": "1", "target_label": "Submit"}
    try:
        await session.request_approval(pred, "Confirm submission", "one", 0)
        token = session.approval["id"]
        await session.handle(server.Command(command="APPROVE", approval_id=token))
        assert session.agent.executions == 1
        with pytest.raises(ValueError):
            await session.handle(server.Command(command="APPROVE", approval_id=token))
        assert session.agent.executions == 1
        await session.request_approval(pred, "Confirm submission", "one", 0)
        token = session.approval["id"]
        await session.submit({"command": "WHISPER", "note": "Do not submit yet"})
        with pytest.raises(ValueError):
            await session.handle(server.Command(command="APPROVE", approval_id=token))
        assert session.agent.executions == 1
    finally:
        session.executor.shutdown(wait=True)


@pytest.mark.anyio
async def test_approval_rejects_changed_page_and_resume_cannot_bypass():
    session = server.AgentSession(Mock(send_json=AsyncMock()))
    session.agent = FakeAgent("https://example.test", "Submit the form")
    session.context = {"normalized_goal": "Submit the form"}
    try:
        await session.request_approval({"operation": "CLICK", "target": "1"}, "Submit", "one", 0)
        with pytest.raises(ValueError):
            await session.handle(server.Command(command="RESUME"))
        session.agent.state["page"]["fingerprint"] = "changed"
        with pytest.raises(ValueError):
            await session.handle(server.Command(command="APPROVE", approval_id=session.approval["id"]))
        assert session.agent.executions == 0
    finally:
        session.executor.shutdown(wait=True)


@pytest.mark.anyio
async def test_multisite_verification_requires_quotes_bound_to_their_source(monkeypatch):
    sources = [
        {"id": "s1", "url": "https://one.test", "text": "Red costs 10", "title": "One"},
        {"id": "s2", "url": "https://two.test", "text": "Blue costs 20", "title": "Two"},
    ]
    response = {"satisfied": True, "reason": "Compared prices", "evidence": [
        {"source_id": "s1", "field": "text", "quote": "Red costs 10"},
        {"source_id": "s2", "field": "text", "quote": "Blue costs 20"},
    ]}
    captured = []

    async def request(name, schema, prompt):
        captured.append(json.loads(prompt))
        return response

    monkeypatch.setattr(claude_sys2, "_request", request)
    good = await claude_sys2.verify_outcome("Compare", "Both prices", {}, [], evidence=sources)
    assert good["satisfied"] is True
    assert captured[-1]["sources"] == sources
    response["evidence"][1]["source_id"] = "s1"
    bad = await claude_sys2.verify_outcome("Compare", "Both prices", {}, [], evidence=sources)
    assert bad["satisfied"] is False
    assert "ground" in bad["reason"].lower()


def test_evidence_survives_navigation_without_duplicate_frames():
    from hyperagent.evidence import EvidenceLedger

    ledger = EvidenceLedger(limit=2)
    first = {"url": "https://one.test", "title": "One", "text": "First result", "fingerprint": "one"}
    ledger.observe(first)
    ledger.observe(first)
    ledger.observe({**first, "url": "https://two.test", "text": "Second result"})
    assert len(ledger.sources) == 2
    assert ledger.sources[0]["text"] == "First result"
    assert ledger.sources[0]["captured_at"]
    ledger.observe({**first, "text": "Third result"})
    assert len(ledger.sources) == 2
    assert len({s["id"] for s in ledger.sources}) == 2


@pytest.mark.anyio
async def test_approval_checks_live_page_even_when_cached_snapshot_matches():
    from hyperagent.browser import BeforeActionStale

    session = server.AgentSession(Mock(send_json=AsyncMock()))
    session.agent = FakeAgent("https://example.test", "Submit the form")
    session.agent.browser = Mock(fresh=Mock(return_value=False))
    session.context = {"normalized_goal": "Submit the form"}
    try:
        await session.request_approval({"operation": "CLICK", "target": "1"}, "Submit", "one", 0)
        with pytest.raises(BeforeActionStale):
            await session.handle(server.Command(command="APPROVE", approval_id=session.approval["id"]))
        assert session.agent.executions == 0
        assert session.approval is None
    finally:
        session.executor.shutdown(wait=True)


@pytest.mark.anyio
async def test_invalid_milestones_do_not_break_preflight(monkeypatch):
    monkeypatch.setattr(claude_sys2, "_request", AsyncMock(return_value={
        "normalized_goal": "Read", "stopping_predicate": "Report visible", "milestones": "not an array",
    }))
    result = await claude_sys2.normalize_goal_and_constraints("Read")
    assert result["milestones"] == []


@pytest.mark.anyio
async def test_extracted_rows_require_their_own_source_quotes(monkeypatch):
    sources = [{"id": "s1", "url": "https://one.test", "text": "Red costs 10", "title": "One"}]
    ref = {"source_id": "s1", "field": "text", "quote": "Red costs 10"}
    response = {"executive_summary": "One observed item", "evidence": [ref],
                "rows": [{"data": {"name": "Red", "price": 10}, "evidence": [ref]}]}
    monkeypatch.setattr(claude_sys2, "_request", AsyncMock(return_value=response))
    result = await claude_sys2.compile_final_deliverable("Compare", "https://one.test", [], [], evidence=sources)
    assert result["available"] is True
    assert result["structured_table"][0]["source_urls"] == ["https://one.test"]
    response["rows"][0]["evidence"] = [{**ref, "source_id": "invented"}]
    result = await claude_sys2.compile_final_deliverable("Compare", "https://one.test", [], [], evidence=sources)
    assert result["available"] is False
    assert result["structured_table"] == []


@pytest.mark.anyio
async def test_failed_verification_returns_feedback_to_recovery_with_a_bound(monkeypatch):
    monkeypatch.setattr(server, "compile_final_deliverable", AsyncMock(return_value={"available": True}))
    monkeypatch.setattr(server, "verify_outcome", AsyncMock(return_value={
        "satisfied": False, "available": True, "reason": "A second source is missing.",
    }))
    session = server.AgentSession(Mock(send_json=AsyncMock()))
    session.agent = FakeAgent("https://example.test", "Compare sources")
    session.context = {"normalized_goal": "Compare sources", "stopping_predicate": "Two sources compared"}
    try:
        session.auto = True
        await session.finish(verify=True)
        assert session.auto is True
        assert "second source" in session.recovery_reason
        assert session.verification_recoveries == 1
        assert server.verify_outcome.call_args.args[1].startswith("Two sources compared")
        session.verification_recoveries = 2
        await session.finish(verify=True)
        assert session.auto is False
        assert session.status == "paused"
        events = [call.args[0] for call in session.ws.send_json.call_args_list]
        assert any(event["type"] == "OUTCOME_UNVERIFIED" for event in events)
        partial = next(event["deliverable"] for event in events if event["type"] == "ARTIFACT_READY")
        assert partial["verified"] is False
        assert "A second source is missing." in partial["unresolved_issues"]
    finally:
        session.executor.shutdown(wait=True)
