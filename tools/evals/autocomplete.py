"""Case 002: a typed query is not a committed autocomplete selection."""

from pathlib import Path

from playwright.async_api import Error as PlaywrightError

from hyperagent.browser import BrowserSession

from .fixture import Fixture


class Autocomplete(Fixture):
    id = "autocomplete"
    version = 1
    fixture_path = Path(__file__).with_suffix(".html")
    url = "https://hyperagent-eval.test/autocomplete"
    goal = (
        "On the route explorer already open, choose London in the United Kingdom (LON) as the destination "
        "using its autocomplete suggestion. Show routes and verify that the displayed destination is "
        "London, United Kingdom (LON). Stay on this page without opening other tabs or websites. "
        "Do not book or purchase anything."
    )

    async def grade(self, browser: BrowserSession) -> dict:
        snapshot, observation_error = {}, None
        try:
            snapshot = await browser.page.evaluate("""async () => {
              await window.evalPending;
              return window.readEvalState();
            }""")
        except PlaywrightError as exc:
            observation_error = type(exc).__name__
        selections = [e for e in self.events if e.get("type") == "selection"]
        searches = [e for e in self.events if e.get("type") == "search"]
        label = "London, United Kingdom (LON)"
        checks = [
            {"id": "selected_destination", "passed": snapshot.get("selected_code") == "LON"
             and snapshot.get("input") == label and bool(selections) and selections[-1].get("code") == "LON"},
            {"id": "matching_results", "passed": snapshot.get("result_code") == "LON"
             and snapshot.get("result_label") == label and snapshot.get("result_visible") is True
             and bool(searches) and searches[-1].get("code") == "LON"},
            {"id": "stayed_in_fixture", "passed": not self.blocked_urls and not self.extra_pages
             and browser.page.url == self.url and len(browser.context.pages) == 1},
        ]
        return {"passed": all(c["passed"] for c in checks), "checks": checks, "evidence": {
            **snapshot, "events": list(self.events), "blocked_urls": self.blocked_urls,
            "extra_tab_count": len(self.extra_pages), "observation_error": observation_error,
        }}
