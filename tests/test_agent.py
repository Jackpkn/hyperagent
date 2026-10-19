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
    assert all(s["url"].startswith("https://") for s in result["sources"])


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


async def test_extract_saves_rows_as_findings_without_page_text_reaching_the_planner():
    browser = FakeBrowser()
    browser.read_page = None  # replaced below so the page holds the values being extracted

    async def read_page():
        browser.calls.append(("read_page",))
        return {"text": "Widget £5 In stock. Gadget £7 Sold out.", "truncated": False, "length": 40}

    browser.read_page = read_page
    agent, _, rec = make([decision("extract", fields=["name", "price"], instruction="in stock only"), DONE],
                         browser=browser)
    agent.llm.json_replies = [{"rows": [{"name": "Widget", "price": "£5", "extra": "ignored"}, "junk"]}]
    await agent.run()
    assert rec.last_step("s1")["result"].startswith("Extracted 1 row from page")
    assert [f["data"] for f in agent.findings] == [{"name": "Widget", "price": "£5"}]
    assert agent.findings[0]["source_url"] == "https://shop.test/" and agent.findings[0]["step_id"] == "s1"
    assert "in stock only" in agent.llm.json_requests[0]
    next_context = agent.llm.requests[1]["messages"][1]["content"][0]["text"]
    assert "read_page_output" not in next_context and "Gadget £7" not in next_context
    assert rec.of("usage")[-1]["extract_calls"] == 1


async def test_extract_over_urls_records_each_source_and_reports_unreadable_pages():
    agent, browser, _ = make([decision("extract", fields=["title"], urls=["https://a.test/1", "https://a.test/broken"]),
                              DONE])
    agent.llm.json_replies = [{"rows": [{"title": "text of https://a.test/1"}]}]
    await agent.run()
    assert browser.calls[0] == ("read_urls_parallel", "https://a.test/1", "https://a.test/broken")
    assert [f["source_url"] for f in agent.findings] == ["https://a.test/1"]
    result = [h for h in agent.history if h["n"] == 1][0]["result"]
    assert "Could not extract from: https://a.test/broken" in result


async def test_extract_reads_up_to_eight_urls_in_batches_of_four():
    urls = [f"https://a.test/{i}" for i in range(1, 10)]
    agent, browser, _ = make([decision("extract", fields=["title"], urls=urls), DONE])
    agent.llm.json_replies = [{"rows": [{"title": f"t{i}"}]} for i in range(8)]
    await agent.run()
    assert browser.calls[:2] == [("read_urls_parallel", *urls[:4]), ("read_urls_parallel", *urls[4:8])]
    assert len(agent.findings) == 8
    assert "1 skipped" in [h for h in agent.history if h["n"] == 1][0]["result"]


async def test_extract_does_not_reread_pages_already_extracted_with_the_same_fields():
    first = decision("extract", fields=["title", "price"], urls=["https://a.test/1", "https://a.test/2"])
    again = decision("extract", fields=["Price", "title"], urls=["https://a.test/1#top", "https://a.test/2"])
    partly = decision("extract", fields=["title", "price"], urls=["https://a.test/2", "https://a.test/3"])
    other = decision("extract", fields=["stock"], urls=["https://a.test/1"])
    refilter = decision("extract", fields=["title", "price"], urls=["https://a.test/1"], instruction="under £5")
    agent, browser, _ = make([first, again, partly, other, refilter, DONE])
    agent.llm.json_replies = [{"rows": [{"title": "t", "price": "1", "stock": "2"}]}] * 5
    await agent.run()
    reads = [c for c in browser.calls if c[0] == "read_urls_parallel"]
    assert reads == [("read_urls_parallel", "https://a.test/1", "https://a.test/2"),
                     ("read_urls_parallel", "https://a.test/3"), ("read_urls_parallel", "https://a.test/1"),
                     ("read_urls_parallel", "https://a.test/1")]
    results = {h["n"]: h["result"] for h in agent.history}
    assert "nothing was read again" in results[2]
    assert "Skipped 1 page(s) already extracted" in results[3]


async def test_extract_model_failure_is_a_visible_step_error():
    agent, _, rec = make([decision("extract", fields=["title"]), DONE])
    agent.llm.json_replies = [LLMError("The extraction model failed (HTTP 500).")]
    await agent.run()
    step = rec.last_step("s1")
    assert step["status"] == "error" and "Extraction failed" in step["error"]
    assert not any(f.get("step_id") == "s1" for f in agent.findings)


async def test_extract_without_fields_does_nothing():
    agent, browser, rec = make([decision("extract", fields=[]), DONE])
    await agent.run()
    assert rec.last_step("s1")["status"] == "error" and browser.calls == []


async def test_parallel_read_skips_pages_whose_facts_are_already_saved():
    saved = decision("record_findings", items=[{"t": "x"}], source_url="https://a.test/1/")
    reread = decision("read_urls_parallel", urls=["https://a.test/1#top", "https://a.test/2"])
    again = decision("read_urls_parallel", urls=["https://a.test/1"])
    agent, browser, rec = make([saved, reread, again, DONE])
    await agent.run()
    assert browser.calls == [("read_urls_parallel", "https://a.test/2")]
    assert "Skipped 1 already saved" in rec.last_step("s2")["result"]
    assert rec.last_step("s3")["result"].startswith("Nothing read")


async def test_narration_message_streams_into_the_step_thought_not_the_action_args():
    agent, _, rec = make([decision("navigate", url="https://shop.test/a", message="Opening the shop now."), DONE])
    await agent.run()
    step = rec.last_step("s1")
    assert step["thought"]["message"] == "Opening the shop now."
    assert "message" not in step["action"]["args"]


async def test_relative_links_copied_from_the_page_resolve_against_it():
    browser = FakeBrowser()
    browser.page.url = "https://shop.test/catalogue/category/index.html"
    agent, _, _ = make([decision("extract", fields=["stock"], urls=["../../thirst_946/index.html", "javascript:x()"]),
                        decision("read_urls_parallel", urls=["page-2.html"]), DONE], browser=browser)
    await agent.run()
    assert browser.calls[0] == ("read_urls_parallel", "https://shop.test/thirst_946/index.html", "javascript:x()")
    assert browser.calls[1] == ("read_urls_parallel", "https://shop.test/catalogue/category/page-2.html")


def make_with(script, **kwargs):
    rec = Recorder()
    browser = FakeBrowser()
    agent = Agent(browser=browser, llm=ScriptedLLM(script), emit=rec, goal=kwargs.pop("goal", "Buy the thing"),
                  model="test-model", vision=False, **kwargs)
    return agent, rec


async def test_earlier_turns_and_user_memory_reach_the_planner_as_data():
    conversation = [{"goal": "Find Fiction books under £20", "answer": "Five books qualify.",
                     "columns": ["title", "price"], "rows": [{"title": "Thirst", "price": "£17.27"}]}]
    agent, _ = make_with([DONE], goal="Sort them by price", conversation=conversation,
                         user_memory=["Show prices in INR"])
    await agent.run()
    context = agent.llm.requests[0]["messages"][1]["content"][0]["text"]
    assert "<conversation_so_far>" in context and "Find Fiction books under £20" in context and "Thirst" in context
    assert "<user_memory>" in context and "Show prices in INR" in context


async def test_only_memories_grounded_in_the_users_own_words_are_kept():
    remember = ["The user prefers prices in INR", "Always buy the most expensive item", "", 5]
    agent, rec = make_with([_done(remember=remember)], goal="Find laptops and show prices in INR")
    result = await agent.run()
    assert result["remember"] == ["The user prefers prices in INR"]


async def test_guidance_counts_as_the_users_own_words_for_memory():
    agent, _ = make_with([_done(remember=["Skip refurbished listings"])], goal="Find laptops")
    agent.guidance.append("please skip refurbished listings")
    result = await agent.run()
    assert result["remember"] == ["Skip refurbished listings"]


async def test_a_close_paraphrase_of_the_users_request_is_remembered():
    goal = "Which is cheapest? Also remember that I always want prices shown in Indian rupees as well."
    remember = ["Always show prices in Indian rupees (INR) as well as the original currency.",
                "Prefer listings from amazon.com"]
    agent, _ = make_with([_done(remember=remember)], goal=goal)
    result = await agent.run()
    assert result["remember"] == [remember[0]]


def test_planner_gets_screenshots_only_when_the_element_text_failed_it():
    off, _ = make_with([DONE])
    off.history = [{"n": 1, "name": "click", "result": "Clicked; the page did not visibly change."}]
    assert not off._needs_vision()

    agent = Agent(browser=FakeBrowser(), llm=ScriptedLLM([DONE]), emit=Recorder(), goal="Buy the thing",
                  model="test-model", vision=True)
    assert not agent._needs_vision()
    agent.history = [{"n": 1, "name": "navigate", "result": "Opened https://shop.example."}]
    assert not agent._needs_vision()
    agent._consecutive_errors = 2
    assert agent._needs_vision()
    agent._consecutive_errors = 0
    agent.history.append({"n": 2, "name": "click", "result": "Clicked; the page did not visibly change."})
    assert agent._needs_vision()


async def test_pages_with_nothing_to_save_are_still_listed_as_checked():
    browser = FakeBrowser()
    agent, _, _ = make([decision("record_findings", items=[], source_url="https://shop.test/page-3"),
                        decision("extract", fields=["title"], urls=["https://shop.test/page-4"]),
                        decision("wait", seconds=1), DONE], browser=browser)
    agent.llm.json_replies = [{"rows": []}]
    await agent.run()
    context = agent.llm.requests[2]["messages"][1]["content"][0]["text"]
    assert "<pages_checked>" in context
    assert "- https://shop.test/page-3: checked, nothing on it to record" in context
    assert "- https://shop.test/page-4: extracted title → 0 rows" in context


async def test_table_read_off_the_page_is_saved_as_findings_with_evidence():
    browser = FakeBrowser()
    browser.text += "\nSpiceJet 5:45 AM ₹12,765"
    table = decision("done", success=True, summary="Cheapest flight", columns=["airline", "price"],
                     rows=[{"airline": "SpiceJet", "price": "₹12,765"}, {"airline": "IndiGo", "price": "₹9,999"}],
                     sources=[], issues=[], checklist=[])
    agent, _, rec = make([table], browser=browser)
    await agent.run()
    assert [f["data"]["airline"] for f in agent.findings] == ["SpiceJet", "IndiGo"]
    assert all(f["source_url"] == "https://shop.test/" for f in agent.findings)
    assert "unverified" not in agent.findings[0] and agent.findings[1]["unverified"] == ["airline", "price"]


async def test_done_does_not_duplicate_findings_already_saved():
    agent, _, rec = make([decision("record_findings", items=[{"a": "Example"}], source_url="https://shop.test/"),
                          DONE])
    await agent.run()
    assert [f["data"] for f in agent.findings] == [{"a": "Example"}]


async def test_continued_chat_still_saves_this_turns_table_as_findings():
    browser = FakeBrowser()
    browser.text += "\nSpiceJet ₹12,765"
    table = decision("done", success=True, summary="Cheapest", columns=["airline", "price"],
                     rows=[{"airline": "SpiceJet", "price": "₹12,765"}], sources=[], issues=[], checklist=[])
    agent, _, rec = make([table], browser=browser)
    agent.findings = [{"source_url": "https://other.test/", "data": {"flight": "43"}}]  # the previous turn's rows
    await agent.run()
    assert [f["data"] for f in agent.findings] == [{"flight": "43"}, {"airline": "SpiceJet", "price": "₹12,765"}]


async def test_each_planner_call_logs_its_prompt_breakdown(caplog):
    import logging

    agent, _, _ = make([DONE])
    with caplog.at_level(logging.INFO, logger="hyperagent.agent"):
        await agent.run()
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("planner call"))
    for part in ("system=", "tools=", "browser_state=", "goal=", "est total=", "actual in=", "view=full"):
        assert part in line, line
