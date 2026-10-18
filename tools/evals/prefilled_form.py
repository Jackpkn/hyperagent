"""Case 001: preserve correct controls while finishing a form. No agent-specific path rules."""

from pathlib import Path

from playwright.async_api import Error as PlaywrightError

from hyperagent.browser import BrowserSession

from .fixture import Fixture

EXPECTED = {"name": "Alex Tester", "email": "alex@example.test", "company": "Example Labs",
            "country": "India", "billing": "Monthly", "newsletter": False}
PRESERVED = {"name", "country", "billing", "newsletter"}


class PrefilledForm(Fixture):
    id = "prefilled-form"
    version = 1
    fixture_path = Path(__file__).with_suffix(".html")
    url = "https://hyperagent-eval.test/prefilled-form"
    goal = (
        "Complete the contact preferences form already open. The required details are Name Alex Tester, "
        "Email alex@example.test, Company Example Labs, Country India, Monthly billing, and Newsletter off. "
        "Leave already-correct controls untouched. Fill the missing fields, then click Review details once "
        "and verify the displayed details. Stay on this page; do not submit a purchase or open other websites."
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
        reviews = [e["values"] for e in self.events if e.get("type") == "review"]
        touches = [e for e in self.events if e.get("control") in PRESERVED]
        checks = [
            {"id": "required_values", "passed": snapshot.get("values") == EXPECTED},
            {"id": "review_matches", "passed": bool(snapshot.get("reviewVisible") and reviews
                                                      and reviews[-1] == EXPECTED)},
            {"id": "review_once", "passed": len(reviews) == 1},
            {"id": "preserved_controls_untouched", "passed": not touches},
            {"id": "stayed_in_fixture", "passed": not self.blocked_urls and browser.page.url == self.url
             and not self.extra_pages and len(browser.context.pages) == 1},
        ]
        return {"passed": all(c["passed"] for c in checks), "checks": checks, "evidence": {
            "values": snapshot.get("values"), "review": reviews[-1] if reviews else None,
            "review_count": len(reviews), "preserved_control_events": touches,
            "blocked_urls": self.blocked_urls, "observation_error": observation_error,
            "extra_tab_count": len(self.extra_pages),
            "events": list(self.events),
        }}
