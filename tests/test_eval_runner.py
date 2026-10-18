import argparse
import asyncio
import json
import sys

import pytest

from hyperagent.browser import BrowserSession
from tools.evals import runner
from tools.run_task import main

from .fakes import ScriptedLLM, decision
from .test_system1 import CONFIG, ScriptedFast, fast


def options(tmp_path):
    return argparse.Namespace(out=str(tmp_path / "trial.json"), no_fast=True, model=None, mode=None,
                              max_steps=12, max_cost=0.25, timeout=30, approve=False, eval_case="prefilled-form")


def install_model(monkeypatch, script):
    model = ScriptedLLM(script)

    async def close():
        pass

    model.close = close
    monkeypatch.setattr(runner, "LLMClient", lambda config: model)
    return model


CLAIM_DONE = decision("done", success=True, summary="Everything is complete.", columns=[], rows=[],
                      sources=[], issues=[], checklist=[])


async def test_report_rejects_agent_claim_without_actual_form_completion(tmp_path, monkeypatch):
    install_model(monkeypatch, [CLAIM_DONE])
    args = options(tmp_path)
    assert await runner.run_case(args) == 1
    report = json.loads((tmp_path / "trial.json").read_text())
    assert report["agent_claimed_success"] is True
    assert report["passed"] is False
    assert report["terminal"] == "done"
    assert report["total_cost_usd"] is None
    assert report["configuration"]["mode"] == "planner-only"
    assert report["events"][-1]["type"] == "status"


async def test_report_accepts_verified_browser_outcome(tmp_path, monkeypatch):
    browser = BrowserSession()
    monkeypatch.setattr(runner, "BrowserSession", lambda: browser)
    model = install_model(monkeypatch, [])
    actions = [("type_text", "Email", {"text": "alex@example.test", "press_enter": False}),
               ("type_text", "Company", {"text": "Example Labs", "press_enter": False}),
               ("click", "Review details", {})]

    async def decide(*args, **kwargs):
        if not actions:
            return CLAIM_DONE
        action, label, fields = actions.pop(0)
        observation = await browser.observe()
        eid = next(e["id"] for e in observation.elements.values() if e["label"].startswith(label))
        return decision(action, element_id=eid, **fields)

    model.decide = decide
    assert await runner.run_case(options(tmp_path)) == 0
    report = json.loads((tmp_path / "trial.json").read_text())
    assert report["passed"] and report["grading"]["passed"]
    assert report["executed_actions"] == 3
    assert report["configuration"]["approval_mode"] == "risky"


async def test_timeout_writes_failed_result_and_closes_browser(tmp_path, monkeypatch):
    model = install_model(monkeypatch, [])

    async def wait_forever(*args, **kwargs):
        await asyncio.Future()

    model.decide = wait_forever
    browser = BrowserSession()
    monkeypatch.setattr(runner, "BrowserSession", lambda: browser)
    args = options(tmp_path)
    args.timeout = 0.05
    assert await runner.run_case(args) == 1
    report = json.loads((tmp_path / "trial.json").read_text())
    assert report["terminal"] == "timeout" and not report["passed"]
    assert any(e["type"] == "result" and not e["success"] for e in report["events"])
    assert report["events"][-1]["state"] == "stopped"
    assert browser.context is None


async def test_existing_report_is_never_overwritten(tmp_path):
    path = tmp_path / "trial.json"
    path.write_text("original evidence")
    with pytest.raises(FileExistsError):
        await runner.run_case(options(tmp_path))
    assert path.read_text() == "original evidence"


async def test_interrupted_trial_preserves_evidence_before_propagating_cancellation(tmp_path, monkeypatch):
    model = install_model(monkeypatch, [])
    deciding = asyncio.Event()

    async def wait_forever(*args, **kwargs):
        deciding.set()
        await asyncio.Future()

    model.decide = wait_forever
    browser = BrowserSession()
    monkeypatch.setattr(runner, "BrowserSession", lambda: browser)
    trial = asyncio.create_task(runner.run_case(options(tmp_path)))
    await asyncio.wait_for(deciding.wait(), timeout=15)
    trial.cancel()
    with pytest.raises(asyncio.CancelledError):
        await trial
    report = json.loads((tmp_path / "trial.json").read_text())
    assert report["terminal"] == "interrupted" and not report["passed"]
    assert report["events"][-1]["state"] == "stopped"
    assert browser.context is None


async def test_jev_trial_uses_real_agent_and_same_independent_grader(tmp_path, monkeypatch):
    install_model(monkeypatch, [decision("delegate", subgoal="Fill the missing details and review once"), CLAIM_DONE])
    policy = ScriptedFast([])
    targets = iter([("TYPE_TEXT", "Email"), ("TYPE_TEXT", "Company"), ("CLICK", "Review details")])

    async def decide(page, **kwargs):
        target = next(targets, None)
        if target is None:
            return fast("SUBGOAL_DONE")
        operation, label = target
        eid = next(e["id"] for e in page.elements.values() if e["label"].startswith(label))
        return fast(operation, eid)

    async def write_text(**kwargs):
        return ("alex@example.test" if kwargs["field"]["label"].startswith("Email") else "Example Labs"), 1

    async def close():
        pass

    policy.decide, policy.write_text, policy.close = decide, write_text, close
    monkeypatch.setattr(runner.FastConfig, "from_env", lambda: CONFIG)
    monkeypatch.setattr(runner, "FastPolicy", lambda config: policy)
    args = options(tmp_path)
    args.no_fast = False
    assert await runner.run_case(args) == 0
    report = json.loads((tmp_path / "trial.json").read_text())
    assert report["configuration"]["mode"] == "planner+jev"
    assert report["recorded_usage"]["fast_calls"] == 4
    assert report["recorded_usage"]["text_calls"] == 2
    assert report["grading"]["passed"]


@pytest.mark.parametrize("arguments", [
    ["--eval-case", "prefilled-form"],
    ["--eval-case", "prefilled-form", "--out", "unused.json", "--approve"],
    ["--eval-case", "prefilled-form", "--out", "unused.json", "--max-cost", "nan"],
    ["--eval-case", "prefilled-form", "--out", "unused.json", "--max-steps", "0"],
])
async def test_invalid_eval_arguments_exit_before_any_model_is_created(arguments, monkeypatch):
    def unexpected_model(config):
        raise AssertionError("invalid arguments must not create a model client")

    monkeypatch.setattr(runner, "LLMClient", unexpected_model)
    monkeypatch.setattr(sys, "argv", ["run_task.py", *arguments])
    with pytest.raises(SystemExit) as exc:
        await main()
    assert exc.value.code == 2
