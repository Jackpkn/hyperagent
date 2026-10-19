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
        self.recent = []

    async def decide(self, page, *, goal, subgoal, recent, guidance):
        self.subgoals.append(subgoal)
        self.recent.append(list(recent))
        item = self.script.pop(0)
        if isinstance(item, asyncio.Event):
            await item.wait()
            item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def write_text(self, **_):
        return self.text, 90


def make(fast_script, planner_script, *, mode="risky", browser=None, configured=True):
    rec = Recorder()
    browser = browser or FakeBrowser()
    agent = Agent(browser=browser, llm=ScriptedLLM(planner_script), emit=rec, goal="Order pizza",
                  model="test-model", approval_mode=mode, vision=False,
                  fast=ScriptedFast(fast_script) if configured else None)
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


@pytest.mark.parametrize("script, reason, count", [
    ([fast("TYPE_TEXT", 1), fast("SUBGOAL_DONE")], "claimed_done", 1),
    ([fast("STUCK")], "stuck", 0),
    ([fast("CLICK", 1, confidence=0.1)], "low_confidence", 0),
    ([FastError("unavailable")], "model_error", 0),
])
async def test_delegation_exports_reason_without_changing_handoff(script, reason, count):
    agent, browser, rec = make(script, [decision("delegate", subgoal="Fill name"), DONE],
                               browser=counter_browser())
    result = await agent.run()
    episodes = result["accounting"]["delegations"]
    assert len(episodes) == 1
    assert episodes[0]["reason"] == reason
    assert episodes[0]["executed_actions"] == count == len(browser.calls)
    assert episodes[0]["completion_claimed"] is (reason == "claimed_done")
    assert rec.last_step("s1")["delegation"] == episodes[0]
    context = agent.llm.requests[1]["messages"][1]["content"][0]["text"]
    assert "episode_id" not in context and "completion_claimed" not in context


async def test_cancelled_delegation_records_episode_without_executing():
    gate = asyncio.Event()
    agent, browser, _ = make([gate, fast("CLICK", 1)], [decision("delegate", subgoal="Click")])
    task = asyncio.create_task(agent._step())
    await wait_for(lambda: agent.fast.subgoals)
    agent.stopped = True
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert browser.calls == []
    episodes = agent.ledger.snapshot()["delegations"]
    assert len(episodes) == 1 and episodes[0]["reason"] == "stopped"


@pytest.mark.parametrize("reason", ["paused", "action_budget", "observation_error"])
async def test_delegation_early_exit_is_measured_without_calling_models(reason):
    from hyperagent.browser import ActionError

    agent, browser, _ = make([], [])
    if reason == "paused":
        agent.paused = True
    elif reason == "action_budget":
        agent.actions_taken = agent.max_steps
    else:
        async def observe(**kwargs):
            raise ActionError("Page unavailable")
        browser.observe = observe
    parent = {"id": "s1"}
    await agent._delegate("Continue", parent)
    assert browser.calls == [] and agent.fast.subgoals == []
    assert parent["delegation"]["reason"] == reason
    assert len(agent.ledger.snapshot()["delegations"]) == 1


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
    assert rec.last_step("s1")["delegation"]["reason"] == "rejected"


@pytest.mark.parametrize("interrupt", ["guide", "pause"])
async def test_interruption_during_fast_decision_discards_it_and_returns_to_planner(interrupt):
    gate = asyncio.Event()
    agent, browser, rec = make([gate, fast("CLICK", 2)], [decision("delegate", subgoal="Click"), DONE])
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: agent.fast.subgoals)
    if interrupt == "guide":
        await agent.guide("Actually choose Small")
    else:
        await agent.pause()
        await agent.resume()
    gate.set()
    await task
    assert browser.calls == [] and "new guidance arrived" in rec.last_step("s1")["result"]
    assert "click" in offered(agent, 1)
    assert rec.last_step("s1")["delegation"]["reason"] == "guidance_changed"


async def test_fast_failure_and_no_change_hand_back():
    agent, _, rec = make([FastError("Jev returned HTTP 500")], [decision("delegate", subgoal="x"), DONE])
    await agent.run()
    assert "Jev failed" in rec.last_step("s1")["result"]
    agent, browser, rec = make([fast("CLICK", 1, irreversible=0)] * 5, [decision("delegate", subgoal="x"), DONE],
                               mode="never")
    await agent.run()
    assert len(browser.calls) == 3 and "did not change the page" in rec.last_step("s1")["result"]
    assert rec.last_step("s1")["delegation"]["reason"] == "no_change"


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
        "CLICK": 0.9, "TYPE_TEXT": 0.05, "SUBGOAL_DONE": 0.03, "STUCK": 0.02}},
        "click_target": {"choice": "2", "confidence": 0.8, "probabilities": {"1": 0.2, "2": 0.8}},
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
    agent, _, rec = make([], [decision("delegate", subgoal="x"), DONE], configured=False)
    await agent.run()
    assert "not configured" in rec.last_step("s1")["error"]


def offered(agent, turn=0):
    return {t["function"]["name"] for t in agent.llm.requests[turn]["tools"]}


@pytest.mark.parametrize("configured", [True, False])
async def test_planner_keeps_direct_ui_available_with_optional_jev(configured):
    agent, browser, rec = make([], [decision("click", element_id=1), DONE], mode="never", configured=configured)
    await agent.run()
    routine = {"click", "type_text", "select_option", "scroll"}
    assert routine <= offered(agent)
    assert ("delegate" in offered(agent)) == configured
    assert {"navigate", "search", "press_key", "go_back", "switch_tab", "close_tab", "read_page",
            "extract", "record_findings", "ask_user", "done"} <= offered(agent)
    assert browser.calls == [("click", 1)]
    assert rec.last_step("s1")["status"] == "ok"


class FormBrowser(FakeBrowser):
    """A small form whose observed values and URL follow the actual actions."""

    def __init__(self, *, filled=False, password=False, fail=None):
        super().__init__(fail=fail)
        self.values = {1: "Ada" if filled else "", 3: ""}
        self.password = password

    async def observe(self, *, screenshot=False):
        page = await super().observe(screenshot=screenshot)
        for eid, value in self.values.items():
            page.elements[eid] = {"id": eid, "tag": "input", "label": "Name" if eid == 1 else "Other",
                                  "type": "password" if self.password and eid == 3 else "text",
                                  "editable": True, "role": "textbox", "value": value,
                                  "rect": {"x": 1, "y": 2, "w": 3, "h": 4}}
        page.elements[2]["label"] = "Continue"
        page.text += str(self.values)
        return page

    async def type_text(self, eid, text, press_enter, *, secret_ok=False):
        result = await super().type_text(eid, text, press_enter, secret_ok=secret_ok)
        self.values[eid] = text
        return result

    async def click(self, eid):
        result = await super().click(eid)
        self.page.url = "https://shop.test/next"
        return result


@pytest.mark.parametrize("filled", [False, True])
async def test_one_delegation_completes_multiple_fields_and_page_transition(filled):
    agent, browser, rec = make(
        [fast("TYPE_TEXT", 1), fast("TYPE_TEXT", 3), fast("CLICK", 2), fast("SUBGOAL_DONE")],
        [decision("delegate", subgoal="Fill both fields with Ada and continue to the next page"), DONE],
        browser=FormBrowser(filled=filled))
    await agent.run()
    assert browser.values == {1: "Ada", 3: "Ada"}
    assert browser.page.url.endswith("/next")
    assert agent.usage["llm_calls"] == 2
    assert len(browser.calls) == (2 if filled else 3)
    assert agent.actions_taken == len(browser.calls) + 2  # delegate and final result
    assert "verify on the page" in rec.last_step("s1")["result"]
    assert "https://shop.test/next" in agent.llm.requests[1]["messages"][1]["content"][0]["text"]
    if filled:
        assert rec.last_step("s2")["status"] == "skipped"
        assert "already holds" in rec.last_step("s1")["result"]
        assert "Skipped:" in agent.fast.recent[1][0] and "Ada" in agent.fast.recent[1][0]
        assert "remaining subgoal" in agent.fast.recent[1][0]


async def test_repeated_noop_fields_hand_back_visibly_without_pausing():
    agent, browser, rec = make([fast("TYPE_TEXT", 1)] * 8,
                               [decision("delegate", subgoal="Fill the fields"), DONE],
                               browser=FormBrowser(filled=True))
    await agent.run()
    assert browser.calls == []
    assert agent.usage["fast_calls"] > 1
    assert agent.usage["fast_calls"] < 8
    assert "did not change the page" in rec.last_step("s1")["result"]
    assert "Jev took 0 actions" in rec.last_step("s1")["result"]
    assert not agent.paused


@pytest.mark.parametrize("inability", [FastError("unavailable"), fast("STUCK"), fast("CLICK", 2, confidence=0.2)])
async def test_jev_inability_allows_multiple_explicit_recovery_decisions(inability):
    agent, browser, rec = make([inability], [decision("delegate", subgoal="Continue"),
                              decision("click", element_id=1), decision("click", element_id=1), DONE], mode="never")
    await agent.run()
    assert "click" in offered(agent, 0)
    assert "click" in offered(agent, 1)
    assert "click" in offered(agent, 2)
    assert browser.calls == [("click", 1), ("click", 1)]
    assert not any(s["status"] == "error" for s in rec.of("step") if s.get("system") == "planner")


async def test_successful_jev_handback_keeps_direct_actions_available():
    agent, browser, rec = make([fast("SUBGOAL_DONE")], [decision("delegate", subgoal="Check fields"),
                              decision("click", element_id=1), DONE], mode="never")
    await agent.run()
    assert "click" in offered(agent, 1)
    assert browser.calls == [("click", 1)]


async def test_direct_password_typing_still_requires_approval_with_jev():
    agent, browser, rec = make([], [decision("type_text", element_id=3, text="secret", press_enter=False),
                              decision("type_text", element_id=1, text="ordinary", press_enter=False,
                                       secret=True), DONE], browser=FormBrowser(password=True), mode="never")
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: rec.of("approval"))
    assert browser.calls == []
    assert "secret" not in str(rec.of("approval")[0]["args"])
    agent.resolve_approval(rec.of("approval")[0]["step_id"], True)
    await task
    assert browser.calls == [("type_text", 3, "secret", False), ("type_text", 1, "ordinary", False)]
    assert len(rec.of("approval")) == 1


@pytest.mark.parametrize("interrupt", ["guide", "pause"])
async def test_interrupt_during_text_helper_discards_pending_fast_action(interrupt):
    entered, gate = asyncio.Event(), asyncio.Event()
    agent, browser, rec = make([fast("TYPE_TEXT", 1)], [decision("delegate", subgoal="Fill name"), DONE])

    async def write_text(**kwargs):
        entered.set()
        await gate.wait()
        return "Ada", 90

    agent.fast.write_text = write_text
    task = asyncio.create_task(agent.run())
    await entered.wait()
    if interrupt == "guide":
        await agent.guide("Wait for my next instruction")
    else:
        await agent.pause()
        await agent.resume()
    gate.set()
    await task
    assert browser.calls == []
    assert rec.last_step("s2")["status"] == "skipped"
    assert "click" in offered(agent, 1)


async def test_guidance_discards_recovery_action_without_limiting_later_actions():
    gate = asyncio.Event()
    agent, browser, rec = make([fast("STUCK")], [decision("delegate", subgoal="Continue"), gate,
                              decision("click", element_id=2), decision("click", element_id=1),
                              decision("click", element_id=1), DONE], mode="never")
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: len(agent.llm.requests) == 2)
    await agent.guide("Use the first control")
    gate.set()
    await task
    assert "click" in offered(agent, 1) and "click" in offered(agent, 2)
    assert "click" in offered(agent, 3)
    assert browser.calls == [("click", 1), ("click", 1)]


async def test_failed_fast_mutation_is_not_replayed_on_handback():
    agent, browser, rec = make([fast("CLICK", 1)], [decision("delegate", subgoal="Continue"), DONE],
                              browser=FormBrowser(fail={"click"}))
    await agent.run()
    assert browser.calls == [("click", 1)]
    assert rec.last_step("s2")["status"] == "error"
    assert rec.last_step("s1")["delegation"]["reason"] == "action_error"
    assert "click" in offered(agent, 1)


@pytest.mark.parametrize("action,expected", [
    (decision("click", element_id=1), ("click", 1)),
    (decision("type_text", element_id=1, text="Ada", press_enter=False), ("type_text", 1, "Ada", False)),
    (decision("select_option", element_id=1, option="Ada"), ("select_option", 1, "Ada")),
    (decision("scroll", direction="down"), ("scroll", "down", 1)),
])
async def test_direct_ui_actions_execute_when_jev_is_configured(action, expected):
    agent, browser, rec = make([], [action, DONE], mode="never")
    await agent.run()
    assert browser.calls == [expected]
    assert rec.last_step("s1")["status"] == "ok"


async def test_jev_done_is_a_claim_until_planner_inspects_current_page():
    agent, _, rec = make([fast("SUBGOAL_DONE")], [decision("delegate", subgoal="Check the form")])
    await agent._step()
    assert agent.result is None
    assert rec.of("result") == []
    assert "verify on the page" in rec.last_step("s1")["result"]


async def test_rejected_fast_action_is_not_automatically_replayed():
    agent, browser, rec = make([fast("CLICK", 2)], [decision("delegate", subgoal="Continue"),
                              DONE])
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: rec.of("approval"))
    agent.resolve_approval(rec.of("approval")[0]["step_id"], False)
    await task
    assert "click" in offered(agent, 1)
    assert browser.calls == []


async def test_reading_after_jev_failure_does_not_remove_direct_click():
    agent, browser, _ = make([fast("STUCK")], [decision("delegate", subgoal="Continue"),
                            decision("read_page"), decision("click", element_id=1), DONE], mode="never")
    await agent.run()
    assert "click" in offered(agent, 1) and "click" in offered(agent, 2)
    assert browser.calls == [("read_page",), ("click", 1)]


async def test_jev_http_422_allows_planner_to_finish_multi_action_recovery():
    requests = []

    def reject(request):
        requests.append(request)
        return httpx.Response(422, json={"detail": "Invalid request"})

    agent, browser, rec = make([], [decision("delegate", subgoal="Fill name and continue"),
        decision("read_page"), decision("type_text", element_id=1, text="Ada", press_enter=False),
        decision("click", element_id=2), DONE], browser=FormBrowser(), mode="never")
    policy = FastPolicy(CONFIG, transport=httpx.MockTransport(reject))
    agent.fast = policy
    try:
        result = await agent.run()
    finally:
        await policy.close()
    assert len(requests) == 1
    assert "HTTP 422" in rec.last_step("s2")["error"]
    assert browser.calls == [("read_page",), ("type_text", 1, "Ada", False), ("click", 2)]
    assert browser.values[1] == "Ada" and browser.page.url == "https://shop.test/next"
    assert result["success"]


async def test_direct_risky_recovery_with_jev_still_waits_for_approval():
    agent, browser, rec = make([fast("STUCK")], [decision("delegate", subgoal="Continue"),
                              decision("click", element_id=2), DONE])
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: rec.of("approval"))
    assert browser.calls == []
    agent.resolve_approval(rec.of("approval")[0]["step_id"], True)
    await task
    assert browser.calls == [("click", 2)]


async def test_unchanged_limit_grants_recovery_without_replaying_actions():
    agent, browser, rec = make([fast("CLICK", 1)] * 8,
                               [decision("delegate", subgoal="Continue"), DONE], mode="never")
    await agent.run()
    assert len(browser.calls) == 3
    assert "did not change the page" in rec.last_step("s1")["result"]
    assert "click" in offered(agent, 1)


async def test_fast_action_budget_returns_control_without_replaying_actions(monkeypatch):
    monkeypatch.setattr("hyperagent.system1.FAST_MAX_ACTIONS", 2)
    agent, browser, rec = make([fast("CLICK", 1)] * 3,
                               [decision("delegate", subgoal="Continue"), DONE], mode="never",
                               browser=counter_browser())
    await agent.run()
    assert len(browser.calls) == 2
    assert "budget" in rec.last_step("s1")["result"]
    assert rec.last_step("s1")["delegation"]["reason"] == "attempt_budget"
    assert "click" in offered(agent, 1)


async def test_guidance_during_fast_approval_discards_action():
    agent, browser, rec = make([fast("CLICK", 2)], [decision("delegate", subgoal="Continue"), DONE])
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: rec.of("approval"))
    await agent.guide("Wait for my next instruction")
    agent.resolve_approval(rec.of("approval")[0]["step_id"], True)
    await task
    assert browser.calls == []
    assert "click" in offered(agent, 1)


async def test_interrupted_planner_recovery_approval_discards_stale_action():
    agent, browser, rec = make([fast("STUCK")], [decision("delegate", subgoal="Continue"),
                              decision("click", element_id=2), decision("click", element_id=1), DONE])
    task = asyncio.create_task(agent.run())
    await wait_for(lambda: rec.of("approval"))
    await agent.guide("Choose the first control instead")
    agent.resolve_approval(rec.of("approval")[0]["step_id"], True)
    await task
    assert browser.calls == [("click", 1)]
    assert "click" in offered(agent, 2) and "click" in offered(agent, 3)


async def test_guidance_during_fast_error_handback_does_not_execute_an_action():
    agent, browser, rec = make([FastError("unavailable")], [decision("delegate", subgoal="Continue"), DONE])

    async def emit(event):
        await rec(event)
        if event["type"] == "step" and event.get("system") == "fast" and event["status"] == "error":
            await agent.guide("Wait for my next instruction")

    agent.emit = emit
    await agent.run()
    assert "click" in offered(agent, 1)
    assert browser.calls == []
