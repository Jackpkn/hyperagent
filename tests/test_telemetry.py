import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from hyperagent.agent import Agent
from hyperagent.anthropic_backend import AnthropicBackend
from hyperagent.fast import FastError, FastPolicy
from hyperagent.llm import LLMClient, LLMConfig, LLMError
from hyperagent.telemetry import RunLedger

from .fakes import DONE, FakeBrowser, Recorder, ScriptedLLM, decision
from .test_anthropic_backend import backend, block, reply
from .test_system1 import CONFIG, FormBrowser


def client(handler):
    return LLMClient(LLMConfig("http://model.test", "key", ("model",), extract_model="extract"),
                     transport=httpx.MockTransport(handler))


async def test_concurrent_runs_and_parallel_extractions_are_isolated():
    async def handler(request):
        await asyncio.sleep(0)
        return httpx.Response(200, json={"model": "resolved", "choices": [{"message": {"content": '{"rows": []}'}}],
                                        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.01}})

    llm = client(handler)
    a, b = RunLedger(), RunLedger()

    async def run(ledger, n):
        with ledger.scope("extract", "s1"):
            await asyncio.gather(*(llm.complete_json("rules", "page") for _ in range(n)))

    try:
        await asyncio.gather(run(a, 2), run(b, 3))
        for ledger, n in ((a, 2), (b, 3)):
            snap = ledger.snapshot()
            assert len(snap["records"]) == n
            assert {r["run_id"] for r in snap["records"]} == {ledger.run_id}
            assert len({r["logical_call_id"] for r in snap["records"]}) == n
            assert snap["summary"]["input_tokens"] == n * 10
            assert snap["summary"]["total_cost_usd"] == pytest.approx(n * 0.01)
            assert snap["records"][0]["resolved_model"] == "resolved"
    finally:
        await llm.close()


async def test_invalid_json_retains_usage_and_missing_cost_is_unknown():
    llm = client(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "bad json"}}],
                                                   "usage": {"prompt_tokens": 9, "completion_tokens": 3}}))
    ledger = RunLedger()
    try:
        with ledger.scope("extract", "s2"), pytest.raises(LLMError):
            await llm.complete_json("rules", "secret page")
        snap = ledger.snapshot()
        assert snap["records"][0]["outcome"] == "invalid_response"
        assert snap["summary"]["input_tokens"] == 9
        assert snap["summary"]["total_cost_usd"] is None
        assert snap["summary"]["unknown_cost_count"] == 1
        assert "secret page" not in str(snap)
    finally:
        await llm.close()


async def test_cancelled_request_is_recorded_without_claiming_zero_cost():
    entered = asyncio.Event()

    async def handler(request):
        entered.set()
        await asyncio.Event().wait()

    llm, ledger = client(handler), RunLedger()
    try:
        with ledger.scope("planner", "s3"):
            task = asyncio.create_task(llm.decide("model", [], []))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        record = ledger.snapshot()["records"][0]
        assert record["outcome"] == "cancelled"
        assert record["input_tokens"] is None and record["cost_usd"] is None
    finally:
        await llm.close()


async def test_native_retry_counts_both_responses_and_unknown_model_rate():
    native, _ = backend([reply(block(type="text", text="no action")),
                         reply(block(type="tool_use", name="wait", input={"seconds": 1}))])
    ledger = RunLedger()
    with ledger.scope("planner", "s1"):
        await native.decide("unpriced-model", [{"role": "user", "content": "go"}], [])
    snap = ledger.snapshot()
    assert [r["outcome"] for r in snap["records"]] == ["invalid_response", "success"]
    assert snap["summary"]["input_tokens"] == 2000
    assert snap["summary"]["total_cost_usd"] is None
    assert len({r["logical_call_id"] for r in snap["records"]}) == 1


async def test_jev_invalid_answer_and_helper_tokens_are_recorded():
    responses = iter([
        {"model": "jev-resolved", "usage": {"input_tokens": 100, "output_tokens": 5}, "answers": {}},
        {"choices": [{"message": {"content": '{"text":"Ada"}'}}],
         "usage": {"prompt_tokens": 20, "completion_tokens": 4, "cost": 0.002}},
    ])
    policy = FastPolicy(CONFIG, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=next(responses))))
    ledger, page = RunLedger(), await FakeBrowser().observe()
    try:
        with ledger.scope("jev", "s2", "s1"), pytest.raises(FastError):
            await policy.decide(page, goal="g", subgoal="s", recent=[], guidance=[])
        with ledger.scope("text", "s3", "s1"):
            assert (await policy.write_text(goal="g", subgoal="s", field={}, page=page, recent=[]))[0] == "Ada"
        snap = ledger.snapshot()
        assert [r["outcome"] for r in snap["records"]] == ["invalid_response", "success"]
        assert snap["summary"]["input_tokens"] == 120
        assert snap["summary"]["known_cost_usd"] == 0.002
        assert snap["summary"]["total_cost_usd"] is None
        assert snap["by_purpose"]["text"]["attempts"] == 1
    finally:
        await policy.close()


async def test_agent_emits_accounting_and_exports_audit_records():
    llm = client(lambda r: httpx.Response(200, json={"choices": [{"message": {"tool_calls": [{"function": {
        "name": "done", "arguments": json.dumps(DONE.args)}}]}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.01}}))
    rec = Recorder()
    agent = Agent(browser=FakeBrowser(), llm=llm, emit=rec, goal="Read", model="model")
    try:
        result = await agent.run()
        record = result["accounting"]["records"][0]
        assert record["purpose"] == "planner" and record["step_id"] == "s1"
        assert rec.of("usage")[-1]["accounting"]["summary"]["total_cost_usd"] == 0.01
        assert "records" not in rec.of("usage")[-1]["accounting"]
        assert agent.usage["cost_usd"] == 0.01  # legacy budget is not counted twice
    finally:
        await llm.close()


async def test_native_cache_tokens_are_not_double_counted_and_records_are_idempotent():
    response = reply(block(type="text", text='{"text":"Ada"}'))
    response.usage.cache_creation_input_tokens = 200
    response.usage.cache_read_input_tokens = 300
    native, _ = backend([response])
    ledger = RunLedger()
    with ledger.scope("text", "s4", "s1"):
        await native.complete_json("claude-haiku-5-5", "rules", "goal")
    from hyperagent.telemetry import CallRecord
    snap = ledger.snapshot()
    ledger.record(CallRecord(**snap["records"][0]))
    assert len(ledger.snapshot()["records"]) == 1
    assert snap["summary"]["input_tokens"] == 1500
    assert snap["summary"]["cache_read_tokens"] == 300
    assert snap["summary"]["cost_basis"] == "estimate"


async def test_http_retry_records_provider_error_separately_from_validated_reply():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"text":"Ada"}'}}],
                                        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "cost": 0.001}})

    policy, ledger = FastPolicy(CONFIG, transport=httpx.MockTransport(handler)), RunLedger()
    try:
        with ledger.scope("text", "s1"):
            await policy.write_text(goal="g", subgoal="s", field={}, page=await FakeBrowser().observe(), recent=[])
        records = ledger.snapshot()["records"]
        assert [r["outcome"] for r in records] == ["provider_error", "success"]
        assert [r["attempt"] for r in records] == [1, 2]
        assert ledger.snapshot()["summary"]["total_cost_usd"] is None
    finally:
        await policy.close()


async def test_failed_planner_attempt_is_visible_while_paused():
    llm = client(lambda r: httpx.Response(401))
    rec = Recorder()
    agent = Agent(browser=FakeBrowser(), llm=llm, emit=rec, goal="Read", model="model")
    try:
        await agent._step()
        assert agent.paused
        assert rec.of("usage")[-1]["accounting"]["summary"]["attempts"] == 1
        assert rec.of("usage")[-1]["accounting"]["summary"]["total_cost_usd"] is None
    finally:
        await llm.close()


async def test_guidance_discards_action_but_keeps_returned_usage_visible():
    entered, gate = asyncio.Event(), asyncio.Event()

    async def handler(request):
        entered.set()
        await gate.wait()
        return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [{"function": {
            "name": "click", "arguments": '{"element_id":1}'}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.02}})

    llm, rec, browser = client(handler), Recorder(), FakeBrowser()
    agent = Agent(browser=browser, llm=llm, emit=rec, goal="Click", model="model")
    try:
        task = asyncio.create_task(agent._step())
        await entered.wait()
        await agent.guide("Wait")
        gate.set()
        await task
        assert browser.calls == []
        assert rec.of("usage")[-1]["accounting"]["summary"]["known_cost_usd"] == 0.02
    finally:
        await llm.close()


async def test_extraction_schema_failure_preserves_usage_as_invalid():
    llm = client(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": '{"wrong":[]}'}}],
                                                   "usage": {"prompt_tokens": 10, "completion_tokens": 5}}))
    agent = Agent(browser=FakeBrowser(), llm=llm, emit=Recorder(), goal="Read", model="model")
    try:
        with agent.ledger.scope("extract", "s1"), pytest.raises(LLMError, match="rows list"):
            await agent._extract_page(["name"], "", "page")
        record = agent.ledger.snapshot()["records"][0]
        assert record["outcome"] == "invalid_response"
        assert record["input_tokens"] == 10
    finally:
        await llm.close()


async def test_cancelled_native_stream_retains_known_input_but_not_complete_cost():
    entered = asyncio.Event()
    message = reply()
    message.model = "resolved-native"
    message.usage.cache_read_input_tokens = 20

    class Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def __aiter__(self):
            yield SimpleNamespace(type="message_start", message=message)
            entered.set()
            await asyncio.Event().wait()

    native = AnthropicBackend("key", client=SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: Stream())))
    ledger = RunLedger()
    with ledger.scope("planner", "s1"):
        task = asyncio.create_task(native.decide("claude-haiku-5-5", [{"role": "user", "content": "go"}], [],
                                                on_delta=lambda _: None))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    record = ledger.snapshot()["records"][0]
    assert record["outcome"] == "cancelled"
    assert record["input_tokens"] == 1020 and record["cache_read_tokens"] == 20
    assert record["resolved_model"] == "resolved-native"
    assert record["output_tokens"] is None and record["cost_usd"] is None


@pytest.mark.parametrize("filled", [False, True])
async def test_delegated_helper_and_noop_usage_belong_to_same_run_and_parent(filled):
    choices = iter(["TYPE_TEXT", "SUBGOAL_DONE"])

    def handler(request):
        body = json.loads(request.content)
        if "questions" not in body:
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"text":"Ada"}'}}],
                                            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "cost": 0.001}})
        operation = next(choices)
        answers = {"irreversible": {"noul": 0}}
        for name, question in body["questions"].items():
            if name == "irreversible":
                continue
            ids = question["criteria"]
            choice = operation if name == "operation" else "1"
            answers[name] = {"choice": choice, "confidence": 1,
                             "probabilities": {key: int(key == choice) for key in ids}}
        return httpx.Response(200, json={"answers": answers, "usage": {"input_tokens": 20, "output_tokens": 5}})

    policy = FastPolicy(CONFIG, transport=httpx.MockTransport(handler))
    browser, rec = FormBrowser(filled=filled), Recorder()
    agent = Agent(browser=browser, llm=ScriptedLLM([decision("delegate", subgoal="Fill name Ada"), DONE]),
                  emit=rec, goal="Fill name", model="model", fast=policy)
    try:
        result = await agent.run()
        accounting = result["accounting"]
        assert [r["purpose"] for r in accounting["records"]] == ["jev", "text", "jev"]
        assert {r["parent_step_id"] for r in accounting["records"]} == {"s1"}
        episode = accounting["delegations"][0]
        assert episode["jev_attempts"] == 2 and episode["text_attempts"] == 1
        assert episode["executed_actions"] == int(not filled) == len(browser.calls)
        assert episode["skipped_actions"] == int(filled)
        assert accounting["summary"]["known_cost_usd"] == 0.001
        assert accounting["summary"]["input_tokens"] == 47
        assert accounting["summary"]["total_cost_usd"] is None
    finally:
        await policy.close()
