import asyncio
import json

import httpx

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
    agent, _, rec = make([], [decision("delegate", subgoal="x"), DONE])
    agent.fast = None
    await agent.run()
    assert "not configured" in rec.last_step("s1")["error"]
