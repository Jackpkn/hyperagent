"""Real headless Chromium against a local page (no network, no model). Skipped if Chromium is missing."""

import pytest

from hyperagent.browser import ActionError, BrowserSession

PAGE = """<!doctype html><title>Form</title>
<h1>Order form</h1>
<p>Fill in your <b>details</b>.</p>
<label>Name <input id=name name=name></label>
<label>Secret <input type=password></label>
<select id=size><option>Small</option><option>Large</option></select>
<div style="display:none"><button>Hidden</button></div>
<button onclick="send()">Send</button>
<script>function send(){const v=id=>document.getElementById(id).value;out.textContent='sent:'+v('name')+':'+v('size')}
</script>
<p id=out></p>
<label><input type=checkbox id=t style="opacity:0;position:absolute">Extra cheese</label>
<div style="height:3000px"></div><a href="#end">Far link</a>"""


@pytest.fixture
async def browser():
    session = BrowserSession()
    try:
        await session.start("data:text/html," + PAGE.replace("#", "%23"))
    except ActionError as exc:
        pytest.skip(f"Chromium unavailable: {exc}")
    yield session
    await session.close()


def element(obs, label):
    return next(e for e in obs.elements.values() if e["label"].startswith(label))


async def test_observation_inlines_elements_in_reading_order(browser):
    obs = await browser.observe()
    assert obs.text.index("Order form") < obs.text.index("<input type=text") < obs.text.index("<button>Send")
    assert "Hidden" not in obs.text
    assert "(below)" in obs.text.split("Far link")[0].rsplit("\n", 1)[-1] + obs.text.split("Far link")[1][:12]
    assert 'type=password' in obs.text and 'value=' not in obs.text.split("type=password")[1].split(">")[0]


async def test_actions_by_element_id(browser):
    obs = await browser.observe()
    await browser.type_text(element(obs, "Name")["id"], "Ada", False)
    size = next(e for e in obs.elements.values() if e["tag"] == "select")
    await browser.select_option(size["id"], "Large")
    await browser.click(element(obs, "Send")["id"])
    after = await browser.observe()
    assert "sent:Ada:Large" in after.text
    with pytest.raises(ActionError, match="no longer exists|approval"):
        secret = next(e for e in after.elements.values() if e["type"] == "password")
        await browser.type_text(secret["id"], "hunter2", False)


async def test_stale_ids_fail_clearly(browser):
    obs = await browser.observe()
    stale = element(obs, "Send")["id"] + 1000
    with pytest.raises(ActionError):
        await browser.click(stale)
    page = await browser.read_page()
    assert "Order form" in page["text"]


async def test_model_cannot_open_local_files(browser):
    with pytest.raises(ActionError, match="Only http and https"):
        await browser.navigate("file:///etc/passwd")


async def test_private_network_is_blocked_for_the_model(browser):
    with pytest.raises(ActionError):
        await browser.navigate("http://127.0.0.1:9/")
    assert any("private" in e for e in browser.events)


async def test_styled_checkbox_is_reachable_through_its_label(browser):
    obs = await browser.observe()
    toggle = next(e for e in obs.elements.values() if e["tag"] == "label")
    assert "checkbox unchecked>Extra cheese" in obs.text
    await browser.click(toggle["id"])
    assert "checkbox checked>Extra cheese" in (await browser.observe()).text


async def test_frozen_page_becomes_a_visible_error_not_a_hang(browser, monkeypatch):
    import hyperagent.browser as module
    monkeypatch.setattr(module, "TIME_SCALE", 0.12)
    await browser.navigate("data:text/html,<button onclick='setTimeout(()=>{while(true){}},50)'>Freeze</button>",
                           trusted=True)
    obs = await browser.observe()
    # The click waits for the page to settle, so it is the click that meets the freeze and reports it.
    with pytest.raises(ActionError, match="stopped responding"):
        await browser.click(next(iter(obs.elements)))
    assert any("replaced by a blank tab" in e for e in browser.events)
    fresh = await browser.observe()
    assert fresh.url == "about:blank"


async def test_date_input_accepts_human_formats(browser):
    page = "<label>When <input type=date id=d></label><label>At <input type=time></label>"
    await browser.navigate("data:text/html," + page, trusted=True)
    obs = await browser.observe()
    date_id, time_id = [e["id"] for e in obs.elements.values()]
    await browser.type_text(date_id, "10/17/2026", False)
    await browser.type_text(time_id, "7:30 PM", False)
    after = await browser.observe()
    assert 'value="2026-10-17"' in after.text and 'value="19:30"' in after.text


async def test_nested_controls_inside_clickable_card_and_gridcells_are_exposed(browser):
    page = (
        '<div role="button" tabindex="0" onclick="void 0">'
        '<input placeholder="Destination">'
        '<div role="gridcell">24</div>'
        '<button>Book now</button>'
        "</div>"
    )
    await browser.navigate("data:text/html," + page, trusted=True)
    obs = await browser.observe()
    labels = [e["label"] for e in obs.elements.values()]
    assert "Destination" in labels
    assert "24" in labels
    assert "Book now" in labels


async def test_submit_input_value_and_unlabeled_select_name(browser):
    page = (
        '<form>'
        '<select name="fromPort"><option>Paris</option><option>Boston</option></select>'
        '<input type="submit" value="Find Flights">'
        "</form>"
    )
    await browser.navigate("data:text/html," + page, trusted=True)
    obs = await browser.observe()
    labels = [e["label"] for e in obs.elements.values()]
    assert "Find Flights" in labels
    assert "fromPort" in labels
    assert not any("Paris Boston" in label for label in labels)


async def test_scroll_handles_inner_scrollable_container(browser):
    page = (
        '<body style="overflow:hidden;margin:0">'
        '<div id="pane" style="height:400px;width:600px;overflow-y:auto">'
        '<div style="height:2000px">Tall inner list</div>'
        "</div></body>"
    )
    await browser.navigate("data:text/html," + page, trusted=True)
    res = await browser.scroll("down", 1.0)
    assert "Scrolled down; now at " in res
    assert "now at 0px" not in res





async def test_unreachable_remote_browser_names_the_setting_and_hides_the_endpoint(monkeypatch, caplog):
    monkeypatch.setenv("BROWSER_WS_URL", "ws://127.0.0.1:9/?token=SECRET123")
    session = BrowserSession()
    with pytest.raises(ActionError) as err:
        await session.start("data:text/html,hi")
    assert "BROWSER_WS_URL" in str(err.value)
    assert "SECRET123" not in str(err.value) and "SECRET123" not in caplog.text
    assert "remote browser" in caplog.text, "the real cause must reach the server log"


async def test_script_driven_link_without_href_is_clickable():
    page = ('<!doctype html><style>.cart{cursor:pointer;display:inline-block;width:40px;height:40px}</style>'
            '<div class=header><a class="cart" data-test="shopping-cart-link" onmousedown="">'
            '<span class=badge style="cursor:pointer">2</span></a></div>'
            '<div style="cursor:pointer" id=card><span>Bike Light</span></div>')
    session = BrowserSession()
    try:
        await session.start("data:text/html," + page)
    except ActionError as exc:
        pytest.skip(f"Chromium unavailable: {exc}")
    try:
        obs = await session.observe()
        labels = [e["label"] for e in obs.elements.values()]
        assert any("2" in label or "cart" in label for label in labels), labels
        assert sum("2" in label for label in labels) == 1, "the badge inside the link is not a second target"
    finally:
        await session.close()


async def test_password_field_reports_filled_without_revealing_it(browser):
    secret = element(await browser.observe(), "Secret")
    assert "empty" in (await browser.observe()).text
    await browser.type_text(secret["id"], "hunter2", False, secret_ok=True)
    obs = await browser.observe()
    assert "hunter2" not in obs.text and "filled" in obs.text


async def test_read_page_drops_page_chrome_and_compacts_links(browser):
    tracked = "https://shop.example/ad/click?url=%2Fitem%2F42%3Fcolor%3Dred%26utm_source%3Dx&sig=" + "z" * 80
    page = f"""<header><a href="https://shop.example/account">Sign in</a></header>
<nav><a href="https://shop.example/deals">Deals menu</a></nav>
<div id="cookie-banner">We use cookies</div>
<main><h1>Results</h1><p>{"Plenty of real listing text. " * 20}</p>
<ul><li><a href="{tracked}">Red widget</a> $9.99</li><li></li>
<li><a href="https://shop.example/item/7/ref=sr_1_2?keywords=widget&qid=123">Blue widget</a>
<a href="https://shop.example/item/7?keywords=widget">Blue widget</a></li></ul>
<button>Fare $120 Select</button></main>
<aside>Sponsored sidebar</aside><footer>Copyright footer</footer>"""
    await browser.navigate("data:text/html," + page.replace("#", "%23"), trusted=True)
    text = (await browser.read_page())["text"]

    assert "Results" in text and "$9.99" in text and "Fare $120" in text
    for noise in ("Sign in", "Deals menu", "cookies", "Sponsored sidebar", "Copyright footer", "utm_source", "zzz"):
        assert noise not in text
    assert "[Red widget](https://shop.example/item/42?color=red)" in text
    assert text.count("https://shop.example/item/7?keywords=widget") == 1
    assert "\n-\n" not in text and not text.endswith("-")
    assert "$9.99\n\n" in text  # each list item is its own block


AUTOCOMPLETE = """<!doctype html><title>Trip</title>
<input id=from role=combobox aria-controls=list aria-label="Where from?"><ul id=list role=listbox></ul>
<script>document.getElementById('from').addEventListener('input', (e) => setTimeout(() => {
  document.getElementById('list').innerHTML = '<li role=option>' + e.target.value + ' (DEL)</li>';
}, 180));</script>"""


async def test_typing_into_autocomplete_waits_for_its_suggestions():
    session = BrowserSession()
    try:
        await session.start("data:text/html," + AUTOCOMPLETE)
    except ActionError as exc:
        pytest.skip(f"Chromium unavailable: {exc}")
    try:
        field = element(await session.observe(), "Where from?")
        await session.type_text(field["id"], "Delhi", False)
        obs = await session.observe()  # the next decision must already see the suggestion
        assert any(e["label"] == "Delhi (DEL)" for e in obs.elements.values()), obs.text
    finally:
        await session.close()


async def test_collapsed_autocomplete_must_be_opened_before_typing(browser):
    await browser.page.set_content('''
      <input aria-label="Location" role="combobox" aria-expanded="false" value="Existing"
        onclick="this.hidden=true; document.getElementById('query').hidden=false;
                 document.getElementById('query').focus()">
      <input id="query" hidden aria-label="Search locations" role="combobox" aria-expanded="true"
        aria-controls="choices" oninput="document.getElementById('choices').innerHTML=
          '<li role=option>North Harbor (NTH)</li>'">
      <ul id="choices" role="listbox"></ul>
    ''')
    obs = await browser.observe()
    location = element(obs, "Location")
    with pytest.raises(ActionError, match="[Oo]pen.*autocomplete|[Cc]lick.*first"):
        await browser.type_text(location["id"], "NTH", False)
    assert await browser.page.get_by_label("Location", exact=True).input_value() == "Existing"
    await browser.click(location["id"])
    opened = await browser.observe()
    query = element(opened, "Search locations")
    assert query.get("focused") is True
    result = await browser.type_text(query["id"], "NTH", False)
    assert "select" in result.lower()
    assert "North Harbor (NTH)" in (await browser.observe()).text


@pytest.mark.parametrize("role", ['role="combobox"', 'aria-autocomplete="list"'])
async def test_autocomplete_waits_for_fresh_suggestions_and_does_not_select_them(browser, role):
    await browser.page.set_content('''
      <input id="location" aria-label="Location" ROLE aria-controls="choices" value="Old">
      <ul id="choices" role="listbox"><li role="option">Old location</li></ul>
      <ul role="listbox"><li role="option">Unrelated suggestion</li></ul>
      <script>document.getElementById('location').addEventListener('input', () => {
        window.inputEvents=(window.inputEvents||0)+1;
        setTimeout(() => {
          const option=document.createElement('li');
          option.setAttribute('role', 'option');
          option.textContent='North Harbor (NTH)';
          option.onclick=()=>window.selected=true;
          document.getElementById('choices').replaceChildren(option);
        }, 650);
      });</script>
    '''.replace("ROLE", role))
    field = element(await browser.observe(), "Location")
    result = await browser.type_text(field["id"], "NTH", False)
    obs = await browser.observe()
    assert "North Harbor (NTH)" in obs.text
    assert "Old location" not in obs.text
    assert element(obs, "Location").get("suggestion_ids") == [element(obs, "North Harbor (NTH)")["id"]]
    assert "select" in result.lower()
    assert await browser.page.evaluate("window.inputEvents") == 1
    assert await browser.page.evaluate("Boolean(window.selected)") is False
    await browser.click(element(obs, "North Harbor (NTH)")["id"])
    assert await browser.page.evaluate("window.selected") is True


async def test_autocomplete_timeout_reports_entered_text_without_retrying(browser, monkeypatch):
    monkeypatch.setattr("hyperagent.browser.SUGGESTION_WAIT_MS", 100)
    await browser.page.set_content('''
      <input aria-label="Location" role="combobox" aria-controls="choices"
        oninput="window.inputEvents=(window.inputEvents||0)+1">
      <ul id="choices" role="listbox"></ul>
    ''')
    field = element(await browser.observe(), "Location")
    with pytest.raises(ActionError, match="[Tt]ext was entered.*suggestion"):
        await browser.type_text(field["id"], "NTH", False)
    assert await browser.page.get_by_label("Location").input_value() == "NTH"
    assert await browser.page.evaluate("window.inputEvents") == 1


async def test_unassociated_options_cannot_confirm_autocomplete_readiness(browser, monkeypatch):
    monkeypatch.setattr("hyperagent.browser.SUGGESTION_WAIT_MS", 150)
    await browser.page.set_content('''
      <input aria-label="Location" role="combobox"
        oninput="setTimeout(() => document.getElementById('other').textContent='Unrelated replacement', 30)">
      <ul role="listbox"><li id="other" role="option">Unrelated option</li></ul>
    ''')
    field = element(await browser.observe(), "Location")
    with pytest.raises(ActionError, match="[Tt]ext was entered.*suggestion"):
        await browser.type_text(field["id"], "NTH", False)
    obs = await browser.observe()
    assert element(obs, "Location").get("suggestion_ids") == []


async def test_autocomplete_identity_survives_reindexing_with_duplicate_labels(browser):
    await browser.page.set_content('''
      <input role="combobox" aria-label="Location" aria-controls="first">
      <ul id="first" role="listbox"><li role="option">First location</li></ul>
      <input role="combobox" aria-label="Location" aria-controls="second">
      <ul id="second" role="listbox"><li role="option">Second location</li></ul>
    ''')
    before = [e for e in (await browser.observe()).elements.values() if e["label"] == "Location"]
    identities = [e.get("autocomplete_id") for e in before]
    assert all(identities) and identities[0] != identities[1]
    await browser.page.evaluate("document.body.prepend(document.createElement('button'))")
    after = [e for e in (await browser.observe()).elements.values() if e["label"] == "Location"]
    assert [e["autocomplete_id"] for e in after] == identities
    assert [e["id"] for e in after] != [e["id"] for e in before]


async def test_click_waits_for_the_page_to_react_before_the_next_observation(browser):
    # A picker that appears a moment after the click must be in the very next observation, or the next decision
    # is made against the page the click started from and repeats it.
    await browser.page.set_content('''
      <button onclick="setTimeout(() => { const d = document.createElement('div'); d.setAttribute('role', 'dialog');
        d.innerHTML = '<p>Pick a date</p><button>Done</button>'; document.body.append(d); }, 200)">Open picker</button>
    ''')
    obs = await browser.observe()
    await browser.click(element(obs, "Open picker")["id"])
    after = await browser.observe()
    assert "Pick a date" in after.text and any(e["label"] == "Done" for e in after.elements.values())


async def test_navigate_refuses_a_reload_but_allows_an_in_page_jump(browser):
    await browser.context.route("https://trip.example/**", lambda route: route.fulfill(
        content_type="text/html", body="<title>Trip</title><input aria-label='Where to'><h2 id=history>History</h2>"))
    await browser.navigate("https://trip.example/search?from=BLR")
    await browser.type_text(element(await browser.observe(), "Where to")["id"], "Delhi", False)
    with pytest.raises(ActionError, match="already on this page"):
        await browser.navigate("https://trip.example/search?from=BLR")
    await browser.navigate("https://trip.example/search?from=BLR#history")  # a section or tab of the same page
    assert browser.page.url == "https://trip.example/search?from=BLR#history"
    assert await browser.page.get_by_label("Where to").input_value() == "Delhi"  # nothing was reloaded


@pytest.mark.parametrize("body", [
    "<pre>" + '{"version": "1.0", "files": []}, ' * 20000 + "</pre>",  # a raw JSON response is one text node
    "<p>" + "".join(f"<a href='/r/{i}'>Release {i}</a> " for i in range(5000)) + "</p>",  # one long inline run
])
async def test_one_huge_block_cannot_exceed_the_page_text_budget(browser, body):
    from hyperagent.browser import TEXT_BUDGET

    await browser.page.set_content(body)
    obs = await browser.observe()
    assert obs.truncated and len(obs.text) <= TEXT_BUDGET + 200
