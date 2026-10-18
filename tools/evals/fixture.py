"""Local browser fixture transport and persistent evidence, used only by eval tooling."""

from pathlib import Path

from hyperagent.browser import BrowserSession


class Fixture:
    url: str
    fixture_path: Path

    def __init__(self):
        self.events: list[dict] = []
        self.blocked_urls: list[str] = []
        self.extra_pages = []

    async def setup(self, browser: BrowserSession) -> None:
        html = self.fixture_path.read_text()
        browser.context.on("page", lambda page: self.extra_pages.append(page))
        await browser.context.expose_binding("recordEvalEvent", lambda source, event: self.events.append(event))

        async def route(request):
            if request.request.url == self.url and request.request.method == "GET":
                await request.fulfill(status=200, content_type="text/html", body=html)
            else:
                self.blocked_urls.append(request.request.url)
                await request.abort("blockedbyclient")

        await browser.context.route("**/*", route)
        await browser.page.goto(self.url)
