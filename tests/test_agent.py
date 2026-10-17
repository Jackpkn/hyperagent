import asyncio

from hyperagent.agent import Agent
from hyperagent.llm import LLMError

from .fakes import DONE, FakeBrowser, Recorder, ScriptedLLM, decision


def make(script, *, mode="risky", browser=None, max_steps=10, key="test-key"):
    rec = Recorder()
    browser = browser or FakeBrowser()
    agent = Agent(browser=browser, llm=ScriptedLLM(script, key=key), emit=rec, goal="Buy the thing",
                  model="test-model", approval_mode=mode, max_steps=max_steps, vision=False)
    return agent, browser, rec


async def wait_for(predicate, timeout=2.0):
    for _ in range(int(timeout / 0.01)):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


async def test_runs_to_done_and_streams_every_stage():
    plan = [{"text": "Open shop", "status": "active"}]
    agent, browser, rec = make([decision("navigate", url="https://shop.test/a", plan=plan), DONE])
    result = await agent.run()
    assert result["success"] and result["rows"] == [{"a": "1"}]
    assert browser.calls == [("navigate", "https://shop.test/a")]
    statuses = [e["status"] for e in rec.of("step") if e["id"] == "s1"]
    assert statuses == ["thinking", "running", "ok"]
    assert rec.of("plan")[0]["items"] == plan
    assert rec.last_step("s1")["thought"]["next_goal"] == "do navigate"
    assert rec.of("result")[0]["sources"][0]["url"] == "https://shop.test/"
    assert rec.of("usage")[-1]["llm_calls"] == 2


async def test_risky_click_waits_for_approval_then_executes_once():
    agent, browser, rec = make([decision("click", element_id=2, irreversible=False), DONE])
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: rec.of("approval"))
    approval = rec.of("approval")[0]
    assert approval["target_label"] == "Place order" and browser.calls == []
    assert agent.resolve_approval(approval["step_id"], True)
    await task
    assert browser.calls == [("click", 2)]
    assert not agent.resolve_approval(approval["step_id"], True), "approval is single use"


async def test_rejected_step_is_never_executed_and_reason_reaches_model():
    agent, browser, rec = make([decision("click", element_id=2, irreversible=True), DONE])
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: rec.of("approval"))
    agent.resolve_approval("s1", False, "wrong item")
    await task
    assert browser.calls == []
    assert rec.last_step("s1")["status"] == "rejected"
    assert "REJECTED by the operator. wrong item" in agent.llm.requests[1]["messages"][1]["content"][0]["text"]


async def test_always_mode_gates_navigation_but_never_mode_does_not():
    agent, _, rec = make([decision("navigate", url="https://x.test"), DONE], mode="always")
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: rec.of("approval"))
    await agent.stop()
    await task
    agent, browser, rec = make([decision("click", element_id=2, irreversible=True), DONE], mode="never")
    await agent.run()
    assert browser.calls == [("click", 2)] and not rec.of("approval")


async def test_guidance_during_thinking_discards_stale_decision():
    gate = asyncio.Event()
    agent, browser, rec = make([gate, decision("navigate", url="https://stale.test"), DONE])
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: agent.state == "thinking")
    await agent.guide("Use the blue one")
    gate.set()
    await task
    assert browser.calls == [], "the decision made before the guidance must not run"
    assert rec.last_step("s1")["status"] == "skipped"
    assert "Use the blue one" in agent.llm.requests[1]["messages"][1]["content"][0]["text"]


async def test_pause_during_thinking_holds_and_resume_continues():
    gate = asyncio.Event()
    agent, browser, rec = make([gate, decision("navigate", url="https://a.test"),
                                decision("navigate", url="https://b.test"), DONE])
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: agent.state == "thinking")
    await agent.pause()
    gate.set()
    await wait_for(lambda: agent.state == "paused")
    assert browser.calls == []
    await agent.resume()
    await task
    assert browser.calls == [("navigate", "https://b.test")]


async def test_stop_produces_honest_partial_result_from_findings():
    gate = asyncio.Event()
    agent, _, rec = make([decision("record_findings", items=[{"name": "Widget", "price": "$5"}],
                                   source_url="https://shop.test/w"), gate])
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: agent.findings and agent.state == "thinking")
    await agent.stop()
    result = await task
    assert result["success"] is False
    assert result["issues"][0].startswith("Stopped before the task finished")
    assert result["rows"] == [{"name": "Widget", "price": "$5"}]
    assert {"title": "https://shop.test/w", "url": "https://shop.test/w"} in result["sources"]


async def test_repeated_failures_pause_with_clear_message():
    browser = FakeBrowser(fail={"click"})
    clicks = [decision("click", element_id=1, irreversible=False) for _ in range(3)]
    agent, _, rec = make([*clicks, DONE], browser=browser, mode="never")
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: agent.state == "paused")
    assert [e for e in rec.of("notice") if "I'm stuck" in e["message"]]
    assert [rec.last_step(f"s{i}")["error"] for i in (1, 2, 3)] == ["click failed"] * 3
    await agent.resume()
    await task


async def test_invalid_model_output_is_reported_not_executed():
    agent, browser, rec = make([decision("format_disk"), decision("navigate"), decision("click", element_id=99,
                                                                                      irreversible=False), DONE])
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: agent.state == "paused")  # three invalid choices in a row count as being stuck
    await agent.resume()
    await task
    assert browser.calls == []
    assert "unknown action" in rec.last_step("s1")["error"]
    assert "without url" in rec.last_step("s2")["error"]
    assert "not on the current page" in rec.last_step("s3")["error"]


async def test_model_outage_pauses_instead_of_failing_silently():
    agent, _, rec = make([LLMError("provider down"), DONE])
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: agent.state == "paused")
    assert any("provider down" in e["message"] for e in rec.of("notice"))
    await agent.resume()
    assert (await task)["success"]


async def test_ask_user_waits_for_answer_and_feeds_it_back():
    agent, _, rec = make([decision("ask_user", question="Which size?"), DONE])
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: rec.of("question"))
    assert agent.state == "awaiting_user"
    await agent.guide("Large")
    await task
    assert rec.last_step("s1")["result"] == "You answered: Large"
    assert "Large" in agent.llm.requests[1]["messages"][1]["content"][0]["text"]


async def test_step_budget_forces_partial_result():
    agent, _, _ = make([decision("navigate", url=f"https://p{i}.test") for i in range(5)], max_steps=2)
    result = await agent.run()
    assert not result["success"] and "Ran out of steps" in result["issues"][0]
    assert agent.llm.requests[-1]["force"] == "done"


async def test_loop_warning_reaches_model_after_repeats():
    same = [decision("navigate", url="https://shop.test/") for _ in range(3)]
    agent, _, _ = make([*same, DONE], mode="never")
    await agent.run()
    assert "repeated the same action 3 times" in agent.llm.requests[3]["messages"][1]["content"][0]["text"]


async def test_result_normalises_rows_and_rejects_non_http_sources():
    agent, _, _ = make([decision("done", success=True, summary="s", columns=[], rows=[{"x": 1, "y": None}],
                                 sources=[{"title": "bad", "url": "javascript:alert(1)"}], issues=[])])
    result = await agent.run()
    assert result["columns"] == ["x", "y"] and result["rows"] == [{"x": "1", "y": ""}]
    assert result["sources"] == []


async def test_stop_while_awaiting_approval_ends_cleanly_without_acting():
    agent, browser, rec = make([decision("click", element_id=2, irreversible=True)])
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: rec.of("approval"))
    await agent.pause()
    assert agent.state == "awaiting_approval", "pause must not hide a pending approval"
    await agent.stop()
    result = await task
    assert browser.calls == [] and not result["success"]
    assert rec.last_step("s1")["status"] == "skipped"


async def test_cost_limit_wraps_up():
    agent, _, rec = make([decision("navigate", url=f"https://p{i}.test") for i in range(5)])
    agent.max_cost_usd = 0.0015
    result = await agent.run()
    assert "cost limit" in result["issues"][0]
