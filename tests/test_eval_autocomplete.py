"""Autocomplete outcome grading against real Chromium, without paid model calls."""

import hashlib
import json
import sys

import pytest

from hyperagent.browser import BrowserSession
from tools.evals import runner
from tools.run_task import main

from .fakes import decision
from .test_eval_runner import CLAIM_DONE, install_model, options
from .test_system1 import CONFIG, ScriptedFast, fast


@pytest.fixture
async def city():
    assert "autocomplete" in getattr(runner, "CASES", {}), "autocomplete eval is not registered"
    browser = BrowserSession()
    try:
        await browser.start("about:blank")
        case = runner.CASES["autocomplete"]()
        await case.setup(browser)
        yield browser, case
    finally:
        await browser.close()


async def choose(browser, label="London, United Kingdom (LON)"):
    await browser.page.get_by_role("combobox", name="Destination").fill("London")
    await browser.page.get_by_role("option", name=label, exact=True).click()


async def show_results(browser):
    await browser.page.get_by_role("button", name="Show routes", exact=True).click()


async def test_selected_suggestion_and_matching_result_pass(city):
    browser, case = city
    await choose(browser)
    await show_results(browser)
    verdict = await case.grade(browser)
    assert verdict["passed"]
    assert verdict["evidence"]["result_code"] == "LON"


async def test_keyboard_selection_is_accepted(city):
    browser, case = city
    field = browser.page.get_by_role("combobox", name="Destination")
    await field.fill("London")
    await field.press("ArrowDown")
    await browser.page.keyboard.press("ArrowDown")
    await browser.page.keyboard.press("Enter")
    await show_results(browser)
    assert (await case.grade(browser))["passed"]


async def test_exact_typed_label_without_selection_fails(city):
    browser, case = city
    await browser.page.get_by_role("combobox").fill("London, United Kingdom (LON)")
    await show_results(browser)
    verdict = await case.grade(browser)
    assert not verdict["passed"]
    assert not next(c for c in verdict["checks"] if c["id"] == "selected_destination")["passed"]


async def test_similarly_named_city_is_not_accepted(city):
    browser, case = city
    await choose(browser, "London, Ontario, Canada (YXU)")
    await show_results(browser)
    assert not (await case.grade(browser))["passed"]


async def test_selection_without_loading_results_is_incomplete(city):
    browser, case = city
    await choose(browser)
    verdict = await case.grade(browser)
    assert not next(c for c in verdict["checks"] if c["id"] == "matching_results")["passed"]


async def test_editing_after_selection_invalidates_selection_and_old_results(city):
    browser, case = city
    await choose(browser)
    await show_results(browser)
    await browser.page.get_by_role("combobox").fill("London, United Kingdom (LON)")
    assert not (await case.grade(browser))["passed"]


async def test_wrong_selection_can_be_corrected_without_automatic_failure(city):
    browser, case = city
    await choose(browser, "London, Ontario, Canada (YXU)")
    await show_results(browser)
    await choose(browser)
    await show_results(browser)
    assert (await case.grade(browser))["passed"]


async def test_reload_does_not_reuse_historical_success(city):
    browser, case = city
    await choose(browser)
    await show_results(browser)
    await browser.page.reload()
    assert not (await case.grade(browser))["passed"]


async def test_temporary_extra_tab_invalidates_otherwise_correct_result(city):
    browser, case = city
    await browser.read_urls_parallel([case.url])
    await choose(browser)
    await show_results(browser)
    assert not (await case.grade(browser))["passed"]


@pytest.mark.parametrize("use_fast", [False, True])
async def test_autocomplete_runner_grades_actual_agent_outcome(tmp_path, monkeypatch, use_fast):
    browser = BrowserSession()
    monkeypatch.setattr(runner, "BrowserSession", lambda: browser)
    args = options(tmp_path)
    args.eval_case, args.no_fast = "autocomplete", not use_fast
    actions = iter([("CLICK", "Destination"), ("TYPE_TEXT", "Destination"),
                    ("CLICK", "London, United Kingdom (LON)"),
                    ("CLICK", "Show routes")])

    def next_action(page):
        item = next(actions, None)
        if item is None:
            return None
        operation, label = item
        eid = next(e["id"] for e in page.elements.values() if e["label"] == label)
        return operation, eid

    if use_fast:
        install_model(monkeypatch, [decision("delegate", subgoal="Choose London UK and show routes"), CLAIM_DONE])
        policy = ScriptedFast([])

        async def decide(page, **kwargs):
            item = next_action(page)
            return fast(*item) if item else fast("SUBGOAL_DONE")

        async def write_text(**kwargs):
            return "London", 1

        async def close():
            pass

        policy.decide, policy.write_text, policy.close = decide, write_text, close
        monkeypatch.setattr(runner.FastConfig, "from_env", lambda: CONFIG)
        monkeypatch.setattr(runner, "FastPolicy", lambda config: policy)
    else:
        model = install_model(monkeypatch, [])

        async def decide(*args, **kwargs):
            item = next_action(await browser.observe())
            if item is None:
                return CLAIM_DONE
            operation, eid = item
            if operation == "TYPE_TEXT":
                return decision("type_text", element_id=eid, text="London", press_enter=False)
            return decision("click", element_id=eid)

        model.decide = decide
    assert await runner.run_case(args) == 0
    report = json.loads((tmp_path / "trial.json").read_text())
    assert report["case"] == "autocomplete"
    assert report["grading"]["evidence"]["result_code"] == "LON"
    fixture_hash = hashlib.sha256(runner.CASES["autocomplete"].fixture_path.read_bytes()).hexdigest()
    assert report["fixture_sha256"] == fixture_hash
    assert report["executed_actions"] == 4


async def test_autocomplete_rejects_false_completion_claim(tmp_path, monkeypatch):
    install_model(monkeypatch, [CLAIM_DONE])
    monkeypatch.setattr(sys, "argv", ["run_task.py", "--eval-case", "autocomplete", "--no-fast",
                                     "--out", str(tmp_path / "trial.json")])
    with pytest.raises(SystemExit) as exc:
        await main()
    assert exc.value.code == 1
    report = json.loads((tmp_path / "trial.json").read_text())
    assert report["case"] == "autocomplete"
    assert report["agent_claimed_success"] is True and not report["passed"]
