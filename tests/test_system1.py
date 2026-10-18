import asyncio
import json

import httpx
import pytest

from hyperagent.agent import Agent
from hyperagent.fast import FastConfig, FastDecision, FastError, FastPolicy, build_request

from .fakes import DONE, FakeBrowser, Recorder, ScriptedLLM, decision

CONFIG = FastConfig(api_key="ts", model="jev-test", min_confidence=0.45, text_base_url="http://text.test",
                    text_api_key="tk", text_model="text-test")


def fast(op, element_id=None, confidence=0.95, irreversible=0.0):
    return FastDecision(operation=op, element_id=element_id, option=None, confidence=confidence,
                        alternatives=[{"label": op, "p": confidence}], irreversible=irreversible, latency_ms=150)


class ScriptedFast:
    def __init__(self, script, text="Ada"):
        self.config = CONFIG
        self.script = list(script)
        self.text = text
        self.subgoals = []

    async def decide(self, page, *, goal, subgoal, recent, guidance):
        self.subgoals.append(subgoal)
        item = self.script.pop(0)
        if isinstance(item, asyncio.Event):
            await item.wait()
            item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def write_text(self, **_):
        return self.text, 90


def make(fast_script, planner_script, *, mode="risky", browser=None):
    rec = Recorder()
    browser = browser or FakeBrowser()
    agent = Agent(browser=browser, llm=ScriptedLLM(planner_script), emit=rec, goal="Order pizza",
                  model="test-model", approval_mode=mode, vision=False, fast=None)
    agent.fast, agent.tools = ScriptedFast(fast_script), agent.tools
    return agent, browser, rec


async def wait_for(predicate):
    for _ in range(200):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


def counter_browser():
    """Each action changes the page text, so no-change detection stays quiet."""
    browser = FakeBrowser()
    original = browser._act

    async def act(name, *args):
        browser.text += f"\n{name}"
        return await original(name, *args)

    browser._act = act
    return browser


async def test_delegation_runs_fast_actions_then_hands_back():
    agent, browser, rec = make([fast("TYPE_TEXT", 1), fast("SUBGOAL_DONE", confidence=0.9)],
                               [decision("delegate", subgoal="Type the name Ada"), DONE],
                               browser=counter_browser())
    result = await agent.run()
    assert result["success"] and browser.calls == [("type_text", 1, "Ada", False)]
    fast_steps = [e for e in rec.of("step") if e.get("system") == "fast" and e["status"] == "ok"]
    assert [s["action"]["label"] for s in fast_steps] == ['Type "Ada" into "Search"', "Subgoal looks complete"]
    assert fast_steps[0]["confidence"] == 0.95 and fast_steps[0]["parent"] == "s1"
    handback = rec.last_step("s1")["result"]
    assert handback.startswith("Jev took 1 action") and "subgoal is done" in handback
    assert agent.usage["fast_calls"] == 2 and agent.usage["text_calls"] == 1
    assert "Jev took 1 action" in agent.llm.requests[1]["messages"][1]["content"][0]["text"]


async def test_low_confidence_returns_control_without_acting():
    agent, browser, rec = make([fast("CLICK", 2, confidence=0.3)],
                               [decision("delegate", subgoal="Click something"), DONE])
    await agent.run()
    assert browser.calls == []
    assert "unsure (30%)" in rec.last_step("s1")["result"]


async def test_fast_irreversible_click_still_needs_approval():
    agent, browser, rec = make([fast("CLICK", 2, irreversible=0.9), fast("SUBGOAL_DONE")],
                               [decision("delegate", subgoal="Place the order"), DONE], browser=counter_browser())
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: rec.of("approval"))
    assert browser.calls == []
    agent.resolve_approval(rec.of("approval")[0]["step_id"], False, "not yet")
    await task
    assert browser.calls == [] and "you rejected an action" in rec.last_step("s1")["result"]


async def test_guidance_during_fast_decision_discards_it_and_returns_to_planner():
    gate = asyncio.Event()
    agent, browser, rec = make([gate, fast("CLICK", 2)], [decision("delegate", subgoal="Click"), DONE])
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: agent.fast.subgoals)
    await agent.guide("Actually choose Small")
    gate.set()
    await task
    assert browser.calls == [] and "new guidance arrived" in rec.last_step("s1")["result"]


async def test_fast_failure_and_no_change_hand_back():
    agent, _, rec = make([FastError("Jev returned HTTP 500")], [decision("delegate", subgoal="x"), DONE])
    await agent.run()
    assert "Jev failed" in rec.last_step("s1")["result"]
    agent, browser, rec = make([fast("CLICK", 1, irreversible=0)] * 5, [decision("delegate", subgoal="x"), DONE],
                               mode="never")
    await agent.run()
    assert len(browser.calls) == 3 and "did not change the page" in rec.last_step("s1")["result"]


async def test_request_offers_only_compatible_targets():
    page = await FakeBrowser().observe()
    page.elements[1].update(role="textbox", editable=True, value="")
    page.elements[2].update(role="button", editable=False)
    body, targets, operations = build_request(page, goal="g", subgoal="s", recent=[], guidance=["be quick"],
                                              model="jev")
    assert set(targets["TYPE_TEXT"]) == {"1"} and set(targets["CLICK"]) == {"1", "2"}
    assert "SELECT" not in operations and "SCROLL_DOWN" not in operations
    assert body["questions"]["operation"]["instructions"]["operator_guidance"] == "be quick"


async def test_policy_validates_jev_answers():
    page = await FakeBrowser().observe()
    page.elements[2].update(role="button", editable=False)
    page.elements[1].update(role="textbox", editable=True)

    def reply(answers):
        return httpx.MockTransport(lambda request: httpx.Response(200, json={"answers": answers}))

    good = {"operation": {"choice": "CLICK", "confidence": 0.9, "probabilities": {
        "CLICK": 0.9, "TYPE_TEXT": 0.03, "TYPE_TEXT_ENTER": 0.02, "SUBGOAL_DONE": 0.03, "STUCK": 0.02}},
        "click_target": {"choice": "2", "confidence": 0.8, "probabilities": {"1": 0.2, "2": 0.8}},
        "type_text_target": {"choice": "999", "confidence": "invalid unused head"},
        "irreversible": {"noul": 0.7}}
    d = await FastPolicy(CONFIG, transport=reply(good)).decide(page, goal="g", subgoal="s", recent=[], guidance=[])
    assert (d.operation, d.element_id, d.confidence, d.irreversible) == ("CLICK", 2, 0.8, 0.7)
    bad = json.loads(json.dumps(good))
    bad["click_target"]["choice"] = "99"
    policy = FastPolicy(CONFIG, transport=reply(bad))
    try:
        await policy.decide(page, goal="g", subgoal="s", recent=[], guidance=[])
    except FastError:
        pass
    else:
        raise AssertionError("an unoffered target must be rejected")


async def test_delegate_unavailable_without_typesafe_key():
    agent, _, rec = make([], [decision("delegate", subgoal="x"), DONE])
    agent.fast = None
    await agent.run()
    assert "not configured" in rec.last_step("s1")["error"]


async def test_retyping_a_field_that_already_holds_the_value_hands_back_at_once():
    browser = counter_browser()
    original = browser.observe

    async def observe(*, screenshot=False):
        obs = await original(screenshot=screenshot)
        obs.elements[1]["value"] = "Ada"
        return obs

    browser.observe = observe
    agent, browser, rec = make([fast("TYPE_TEXT", 1), fast("TYPE_TEXT", 1)],
                               [decision("delegate", subgoal="Type the name Ada, then the password"), DONE],
                               browser=browser)
    await agent.run()
    assert not any(c[0] == "type_text" for c in browser.calls)
    handback = rec.last_step("s1")["result"]
    assert "already holds" in handback


async def test_isolated_planner_click_is_executed_by_jev():
    agent, browser, rec = make([fast("CLICK", 1)], [decision("click", element_id=1), DONE])
    await agent.run()
    assert browser.calls == [("click", 1)]
    assert agent.usage["fast_calls"] == 1
    assert rec.last_step("s1")["action"]["name"] == "delegate"


async def test_stateful_targets_offer_only_changes_and_never_plain_click():
    page = await FakeBrowser().observe()
    page.elements[1].update(role="tab", selected="true", label="Monthly")
    page.elements[2].update(role="checkbox", checked=True, label="Email updates")
    body, targets, operations = build_request(page, goal="g", subgoal="s", recent=[], guidance=[], model="jev")
    assert "1" not in targets.get("CLICK", {})
    assert "2" not in targets.get("CLICK", {})
    assert "1" not in targets.get("ACTIVATE", {})
    assert "1" not in targets.get("DEACTIVATE", {})
    assert "2" in targets["DEACTIVATE"]
    assert "ACTIVATE" not in operations
    assert body["state"]["elements"][0]["selected"] == "true"


async def test_selected_monthly_skips_before_calling_jev():
    browser = FakeBrowser()
    original = browser.observe
    async def observe(**kwargs):
        page = await original(**kwargs)
        page.elements[1].update(role="tab", selected="true", label="Monthly")
        return page
    browser.observe = observe
    agent, _, rec = make([], [decision("click", element_id=1, desired_state=True), DONE], browser=browser)
    await agent.run()
    assert browser.calls == [] and agent.usage["fast_calls"] == 0
    assert rec.last_step("s1")["status"] == "skipped"


async def test_guidance_during_text_helper_discards_value():
    agent, browser, rec = make([fast("TYPE_TEXT", 1)], [decision("delegate", subgoal="Fill name"), DONE])
    async def text(**kwargs):
        await agent.guide("Use a different name")
        return "Old name", 100
    agent.fast.write_text = text
    await agent.run()
    assert browser.calls == []
    assert rec.last_step("s2")["status"] == "skipped"


async def test_risk_flag_survives_automatic_jev_routing():
    agent, browser, rec = make([fast("CLICK", 1)], [decision("click", element_id=1, irreversible=True), DONE])
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: rec.of("approval"))
    approval = rec.of("approval")[0]
    assert approval['step_id'] != 's1'
    agent.resolve_approval(approval['step_id'], False)
    await task
    assert browser.calls == []


@pytest.mark.parametrize('operation', ['ACTIVATE', 'DEACTIVATE'])
async def test_explicit_toggle_intent_reaches_browser(operation):
    browser = counter_browser()
    original = browser.observe
    async def observe(**kwargs):
        page = await original(**kwargs)
        page.elements[1].update(role="checkbox", checked=operation == 'DEACTIVATE')
        return page
    browser.observe = observe
    agent, _, _ = make([fast(operation, 1), fast("SUBGOAL_DONE")],
                       [decision("delegate", subgoal="Set checkbox state"), DONE], browser=browser)
    await agent.run()
    assert browser.calls == [("click", 1)]


async def test_jev_failure_allows_one_fresh_planner_recovery_then_routes_back():
    agent, browser, rec = make([FastError("offline failure"), fast("CLICK", 1)],
                               [decision("click", element_id=1), decision("click", element_id=1),
                                decision("click", element_id=1), DONE])
    await agent.run()
    assert browser.calls == [("click", 1), ("click", 1)]
    assert len(agent.fast.subgoals) == 2
    assert any("one recovery action" in n["message"] for n in rec.of("notice"))


async def test_control_becoming_selected_during_approval_is_not_clicked():
    agent, browser, rec = make([fast("ACTIVATE", 1)], [decision("click", element_id=1), DONE], mode="always")
    async def current_state(eid):
        return {"role": "tab", "selected": "true"}
    browser.element_state = current_state
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: rec.of("approval"))
    agent.resolve_approval(rec.of("approval")[0]["step_id"], True)
    await task
    assert browser.calls == []
    assert rec.last_step("s2")["status"] == "skipped"
    assert "Already selected" in rec.last_step("s2")["result"]


async def test_pause_then_resume_during_approval_still_discards_old_decision():
    agent, browser, rec = make([fast("CLICK", 1)], [decision("click", element_id=1), DONE], mode="always")
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: rec.of("approval"))
    await agent.pause()
    await agent.resume()
    agent.resolve_approval(rec.of("approval")[0]["step_id"], True)
    await task
    assert browser.calls == []
    assert rec.last_step("s2")["status"] == "skipped"


async def test_password_stays_direct_and_approved_with_jev_enabled():
    browser = FakeBrowser()
    original = browser.observe
    async def observe(**kwargs):
        page = await original(**kwargs)
        page.elements[1].update(type="password")
        return page
    browser.observe = observe
    agent, _, rec = make([], [decision("type_text", element_id=1, text="private", press_enter=False), DONE],
                         browser=browser, mode="never")
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: rec.of("approval"))
    agent.resolve_approval(rec.of("approval")[0]["step_id"], True)
    await task
    assert agent.usage["fast_calls"] == 0 and browser.calls == [("type_text", 1, "private", False)]
    assert "private" not in json.dumps(rec.events)


async def test_type_and_enter_is_preserved_even_when_text_already_matches():
    agent, browser, _ = make([fast("TYPE_TEXT_ENTER", 1)],
                             [decision("type_text", element_id=1, text="Ada", press_enter=True), DONE], mode="never")
    async def current_state(eid):
        return {"value": "Ada", "type": "text"}
    browser.element_state = current_state
    await agent.run()
    assert browser.calls == [("type_text", 1, "Ada", True)]
    assert '"press_enter": true' in agent.fast.subgoals[0]


async def test_disabled_and_selected_dropdown_targets_are_not_offered():
    page = await FakeBrowser().observe()
    page.elements[1].update(disabled=True)
    page.elements[2].update(tag="select", options=["Small", "Large"], value="Small")
    _, targets, operations = build_request(page, goal="g", subgoal="s", recent=[], guidance=[], model="jev")
    assert "CLICK" not in operations
    assert [t["option"] for t in targets["SELECT"].values()] == ["Large"]


async def test_same_failed_control_pauses_across_delegations_and_navigation():
    browser = FakeBrowser(fail={"click"})
    original = browser.observe
    async def observe(**kwargs):
        page = await original(**kwargs)
        if browser.calls:
            page.elements[11] = {**page.elements.pop(1), "id": 11}
        return page
    browser.observe = observe
    agent, _, rec = make([fast("CLICK", 1), fast("CLICK", 11)],
                         [decision("delegate", subgoal="Use Search"),
                          decision("navigate", url="https://shop.test/"),
                          decision("delegate", subgoal="Try Search again"), DONE], browser=browser)
    task = asyncio.create_task(agent.run())
    try:
        await wait_for(lambda: agent.state == "paused" or task.done())
        assert agent.state == "paused", "failure must pause before another paid planner call"
        assert len(agent.llm.requests) == 3
        assert len([call for call in browser.calls if call[0] == "click"]) == 2
        assert any("same control" in n["message"] for n in rec.of("notice"))
        await agent.resume()
        await task
        assert rec.of("result")
    finally:
        if not task.done():
            await agent.stop()
            await task


async def test_guidance_during_readiness_check_discards_action():
    agent, browser, rec = make([fast("CLICK", 1)], [decision("click", element_id=1), DONE])
    async def prepare(name, args):
        await agent.guide("Use a different control")
        return {}
    browser.prepare_action = prepare
    await agent.run()
    assert browser.calls == []
    assert rec.last_step("s2")["status"] == "skipped"
