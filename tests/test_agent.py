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


async def test_plan_step_advances_progress_without_resending_the_plan():
    plan = [{"text": "Open site", "status": "active"}, {"text": "Pick category", "status": "pending"},
            {"text": "Open item", "status": "pending"}]
    agent, _, rec = make([decision("navigate", url="https://shop.test/a", plan=plan, plan_step=1),
                          decision("scroll", direction="down", plan_step=3), DONE])
    await agent.run()
    progress = [[p["status"] for p in e["items"]] for e in rec.of("plan")]
    assert progress[0] == ["active", "pending", "pending"]
    assert progress[1] == ["done", "done", "active"]
    assert progress[-1] == ["done", "done", "done"], "a successful done closes the plan"


async def test_failed_done_leaves_unfinished_plan_items_open():
    plan = [{"text": "Open site", "status": "done"}, {"text": "Find price", "status": "active"}]
    failed = decision("done", success=False, summary="Not found", columns=[], rows=[], sources=[],
                      issues=["no price"])
    agent, _, rec = make([decision("scroll", direction="down", plan=plan), failed])
    await agent.run()
    assert [p["status"] for p in rec.of("plan")[-1]["items"]] == ["done", "active"]


def _done(**extra):
    base = dict(success=True, summary="All set", columns=["a"], rows=[{"a": "1"}],
                sources=[{"title": "Shop", "url": "https://shop.test/"}], issues=[])
    return decision("done", **{**base, **extra})


async def test_checklist_links_evidence_to_real_steps_and_drops_bogus_ones():
    checklist = [{"requirement": "Open the shop", "met": True, "evidence": "Shop home loaded", "step": 1},
                 {"requirement": "Report the price", "met": True, "evidence": "£5 shown", "step": 99},
                 {"requirement": "", "met": True}, "junk"]
    agent, _, rec = make([decision("navigate", url="https://shop.test/a"),
                          _done(checklist=checklist, assumptions=["Prices in GBP", ""],
                                follow_ups=["Compare with other shops", 7, "a", "b", "c"])])
    result = await agent.run()
    assert result["success"]
    assert result["checklist"] == [
        {"requirement": "Open the shop", "met": True, "evidence": "Shop home loaded", "step_id": "s1", "step_n": 1},
        {"requirement": "Report the price", "met": True, "evidence": "£5 shown"},
    ]
    assert result["assumptions"] == ["Prices in GBP"]
    assert result["follow_ups"] == ["Compare with other shops", "a", "b"]
    assert rec.of("result")[0]["checklist"][0]["step_id"] == "s1"


async def test_unmet_checklist_item_downgrades_a_success_claim():
    checklist = [{"requirement": "Find the price", "met": False, "evidence": "Price hidden behind login"}]
    agent, _, _ = make([_done(checklist=checklist)])
    result = await agent.run()
    assert not result["success"]
    assert any("Find the price" in issue for issue in result["issues"])


async def test_result_fields_default_to_empty_lists():
    agent, _, _ = make([DONE])
    result = await agent.run()
    assert result["checklist"] == [] and result["assumptions"] == [] and result["follow_ups"] == []


async def test_richer_finding_replaces_its_partial_copy_from_the_same_page():
    record = lambda items: decision("record_findings", items=items, source_url="https://shop.test/a")  # noqa: E731
    agent, _, rec = make([record([{"title": "Widget"}]),
                          record([{"title": "Widget", "price": "£5"}]),
                          record([{"title": "Widget"}]),
                          record([{"title": "Gadget", "price": "£7"}]), DONE])
    await agent.run()
    assert [f["data"] for f in rec.of("findings")[-1]["items"]] == [
        {"title": "Widget", "price": "£5"}, {"title": "Gadget", "price": "£7"}]
