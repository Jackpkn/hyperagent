"""Independent eval graders against a real browser; no model APIs are called."""

import pytest
from playwright.async_api import Error as PlaywrightError

from hyperagent.browser import BrowserSession
from tools.evals.prefilled_form import PrefilledForm


@pytest.fixture
async def form():
    browser = BrowserSession()
    try:
        await browser.start("about:blank")
        case = PrefilledForm()
        await case.setup(browser)
        yield browser, case
    finally:
        await browser.close()


async def finish_form(browser):
    await browser.page.get_by_label("Email", exact=True).fill("alex@example.test")
    await browser.page.get_by_label("Company", exact=True).fill("Example Labs")
    await browser.page.get_by_role("button", name="Review details").click()


async def test_correct_form_passes_independently_of_agent_claim(form):
    browser, case = form
    await finish_form(browser)
    verdict = await case.grade(browser)
    assert verdict["passed"]
    assert all(check["passed"] for check in verdict["checks"])
    assert verdict["evidence"]["review"]["email"] == "alex@example.test"


async def test_unfinished_form_fails_without_trusting_a_done_message(form):
    browser, case = form
    verdict = await case.grade(browser)
    assert not verdict["passed"]
    failed = {check["id"] for check in verdict["checks"] if not check["passed"]}
    assert {"required_values", "review_matches"} <= failed


@pytest.mark.parametrize("control", ["Name", "Monthly", "Country", "Newsletter"])
async def test_touching_already_correct_control_fails_even_if_final_value_matches(form, control):
    browser, case = form
    if control == "Name":
        await browser.page.get_by_label(control, exact=True).fill("Alex Tester")
    else:
        await browser.page.get_by_label(control, exact=True).click()
        if control == "Newsletter":
            await browser.page.get_by_label(control, exact=True).click()
    await finish_form(browser)
    verdict = await case.grade(browser)
    assert not verdict["passed"]
    assert not next(c for c in verdict["checks"] if c["id"] == "preserved_controls_untouched")["passed"]


async def test_reviewing_incomplete_form_then_editing_requires_fresh_review(form):
    browser, case = form
    await browser.page.get_by_role("button", name="Review details").click()
    await browser.page.get_by_label("Email", exact=True).fill("alex@example.test")
    await browser.page.get_by_label("Company", exact=True).fill("Example Labs")
    verdict = await case.grade(browser)
    assert not verdict["passed"]
    assert not next(c for c in verdict["checks"] if c["id"] == "review_matches")["passed"]


async def test_reload_cannot_erase_unnecessary_control_actions(form):
    browser, case = form
    await browser.page.get_by_label("Monthly", exact=True).click()
    await browser.page.reload()
    await finish_form(browser)
    assert not (await case.grade(browser))["passed"]


async def test_fixture_blocks_external_navigation_and_records_violation(form):
    browser, case = form
    with pytest.raises(PlaywrightError):
        await browser.page.goto("https://example.org/unexpected")
    verdict = await case.grade(browser)
    assert not verdict["passed"]
    assert not next(c for c in verdict["checks"] if c["id"] == "stayed_in_fixture")["passed"]


async def test_closed_extra_tab_still_fails_fixture_constraint(form):
    browser, case = form
    await browser.read_urls_parallel([case.url])
    await finish_form(browser)
    verdict = await case.grade(browser)
    assert not next(c for c in verdict["checks"] if c["id"] == "stayed_in_fixture")["passed"]
