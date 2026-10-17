"""Tests for Claude System 2 integration and fallback synthesis."""

import json

import httpx
import httpx2
import pytest

from hyperagent.claude_sys2 import (
    _table_to_csv,
    compile_final_deliverable,
    normalize_goal_and_constraints,
)


@pytest.mark.anyio
async def test_offline_preflight_preserves_goal_without_inventing_constraints():
    raw = "Read the report published on Saturday, Oct 18, 2026"
    norm = await normalize_goal_and_constraints(raw)
    assert norm["normalized_goal"] == raw
    assert norm["available"] is False
    assert "stopping_predicate" in norm


@pytest.mark.anyio
async def test_compile_deliverable_offline():
    elements = [
        {"index": "1", "role": "button", "label": "Annual Report — 2026 edition", "value": ""},
        {"index": "2", "role": "button", "label": "Research Notes — revised edition", "value": ""},
    ]
    deliverable = await compile_final_deliverable(
        goal="Find the latest reports",
        url="https://example.test/reports",
        elements=elements,
        history=[{"step": 1, "operation": "CLICK"}],
        preflight_note="Requested reports",
    )
    assert len(deliverable["structured_table"]) >= 2
    assert "executive_summary" in deliverable
    assert "csv_content" in deliverable
    assert "json_content" in deliverable
    assert len(deliverable["citations"]) > 0


def test_table_to_csv():
    rows = [{"name": "A", "price": 100}, {"name": "B", "price": 200}]
    csv_str = _table_to_csv(rows)
    assert "name,price" in csv_str
    assert "A,100" in csv_str


@pytest.mark.anyio
async def test_offline_extraction_never_fabricates_success():
    result = await compile_final_deliverable("Find a book", "https://example.test", [], [])
    assert result["structured_table"] == []
    assert result["verified"] is False


@pytest.mark.anyio
async def test_offline_deadlock_does_not_guess_a_click_or_success():
    from hyperagent.claude_sys2 import resolve_system1_deadlock

    result = await resolve_system1_deadlock("Read a report", "https://example.test",
                                            [{"index": "1", "label": "Search reports"}], [], "cycle")
    assert result["action"] == "BLOCKED"


@pytest.mark.anyio
@pytest.mark.parametrize("satisfied,quotes,expected", [
    (True, ["Report opened"], True), (True, ["Invented result"], False),
    (True, [], False), (False, ["Report opened"], False),
])
async def test_verification_requires_positive_judgment_and_observed_evidence(monkeypatch, satisfied, quotes, expected):
    from hyperagent import claude_sys2

    async def response(*_args):
        return {"satisfied": satisfied, "evidence_quotes": quotes, "reason": "Review result"}

    monkeypatch.setattr(claude_sys2, "_request", response)
    result = await claude_sys2.verify_outcome("Read the report", "Report is open", {"text": "Report opened"}, [])
    assert result["satisfied"] is expected


@pytest.mark.anyio
async def test_openrouter_uses_existing_text_key_and_parses_named_tool(monkeypatch):

    monkeypatch.setenv("SYS2_PROVIDER", "openrouter")
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("TEXT_MODEL", "inception/mercury-2.5")
    monkeypatch.setenv("SYS2_REASONING", "none")

    def respond(request):
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-openrouter-key"
        body = json.loads(request.content)
        assert body["model"] == "inception/mercury-2.5"
        assert body["tool_choice"] == {"type": "function", "function": {"name": "normalize_goal"}}
        assert body["reasoning"] == {"enabled": False}
        return httpx.Response(200, json={
            "model": "inception/mercury-2.5", "usage": {"total_tokens": 42},
            "choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": "call_1", "type": "function", "function": {
                    "name": "normalize_goal", "arguments": json.dumps({
                        "normalized_goal": "Read the report", "stopping_predicate": "Report visible",
                        "calendar_warning": None, "constraints": [],
                    }),
                }}]}}],
        })

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    result = await normalize_goal_and_constraints("Read the report")
    assert result["available"] is True
    assert result["normalized_goal"] == "Read the report"
    assert result["provider"] == "openrouter"
    assert result["usage"]["total_tokens"] == 42


@pytest.mark.anyio
@pytest.mark.parametrize("response,status", [
    ({"error": {"message": "Unauthorized"}}, 401),
    ({"choices": [{"finish_reason": "length", "message": {"tool_calls": []}}]}, 200),
    ({"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{"function": {
        "name": "verify_outcome", "arguments": "invalid json",
    }}]}}]}, 200),
    ({"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{"function": {
        "name": "wrong_tool", "arguments": "{\"satisfied\": true}",
    }}]}}]}, 200),
])
async def test_openrouter_bad_responses_cannot_verify_success(monkeypatch, response, status):
    from hyperagent import claude_sys2

    monkeypatch.setenv("SYS2_PROVIDER", "openrouter")
    monkeypatch.setenv("SYS2_API_KEY", "test-key")
    original = httpx.AsyncClient
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=response)

    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    result = await claude_sys2.verify_outcome("Read report", "Report visible", {"text": "Report visible"}, [])
    assert result["available"] is False
    assert result["satisfied"] is False
    assert len(calls) == 1  # No hidden retries or fallback billing.


@pytest.mark.anyio
async def test_anthropic_remains_selectable_and_uses_its_own_key(monkeypatch):
    from hyperagent import claude_sys2

    monkeypatch.setenv("SYS2_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "other-provider-key")
    monkeypatch.setenv("SYS2_MODEL", "configured-anthropic-model")

    def respond(request):
        assert request.headers["x-api-key"] == "anthropic-test-key"
        body = json.loads(request.content)
        assert body["model"] == "configured-anthropic-model"
        assert body["tool_choice"] == {"type": "tool", "name": "verify_outcome"}
        return httpx2.Response(200, json={
            "id": "msg_test", "type": "message", "role": "assistant",
            "model": "configured-anthropic-model", "stop_reason": "tool_use", "stop_sequence": None,
            "usage": {"input_tokens": 12, "output_tokens": 24},
            "content": [{"type": "tool_use", "id": "tool_test", "name": "verify_outcome",
                         "input": {"satisfied": True, "reason": "Observed report",
                                   "evidence_quotes": ["Report visible"]}}],
        })

    original = claude_sys2.AsyncAnthropic
    monkeypatch.setattr(claude_sys2, "AsyncAnthropic", lambda **kw: original(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)), **kw))
    result = await claude_sys2.verify_outcome("Read report", "Report visible", {"text": "Report visible"}, [])
    assert result["satisfied"] is True
    assert result["provider"] == "anthropic"
