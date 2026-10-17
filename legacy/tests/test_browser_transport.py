"""Browser transport selection and ownership without opening a real browser."""

from unittest.mock import Mock

import pytest

from hyperagent import browser


@pytest.mark.parametrize("remote", [True, False])
def test_playwright_transport_owns_an_isolated_context(monkeypatch, remote):
    runtime = Mock()
    chromium = runtime.chromium
    connection = chromium.connect_over_cdp.return_value if remote else chromium.launch.return_value
    monkeypatch.setattr(browser, "sync_playwright", Mock(return_value=Mock(start=Mock(return_value=runtime))),
                        raising=False)
    monkeypatch.delenv("CDP_WS_URL", raising=False)
    monkeypatch.delenv("BROWSER_WS_URL", raising=False)
    if remote:
        monkeypatch.setenv("BROWSER_WS_URL", "wss://browser.example.test/session")
    instance = browser.Browser("https://example.test")
    if remote:
        chromium.connect_over_cdp.assert_called_once_with("wss://browser.example.test/session")
        chromium.launch.assert_not_called()
    else:
        chromium.launch.assert_called_once_with(headless=True)
    connection.new_context.assert_called_once()
    instance.close()
    connection.new_context.return_value.close.assert_called_once()
    runtime.stop.assert_called_once()
    if remote:
        connection.close.assert_not_called()


def test_model_wait_keeps_browser_preview_on_owning_thread():
    import threading

    owner = threading.get_ident()
    ready = threading.Event()
    preview_threads = []
    instance = browser.Browser.__new__(browser.Browser)
    instance.on_frame = lambda frame: None

    def preview():
        preview_threads.append(threading.get_ident())
        ready.set()

    instance.preview = preview

    def model():
        assert threading.get_ident() != owner
        assert ready.wait(2)
        return {'operation': 'WAIT'}

    assert instance.run_model(model) == {'operation': 'WAIT'}
    assert preview_threads and all(thread == owner for thread in preview_threads)


def test_newly_opened_tab_becomes_observation_target():
    instance = browser.Browser.__new__(browser.Browser)
    old = Mock(is_closed=Mock(return_value=False))
    new = Mock(is_closed=Mock(return_value=False))
    instance.page = old
    instance.session = Mock()
    instance.context = Mock(pages=[old, new])
    instance._adopt_latest_page()
    assert instance.page is new
    instance.context.new_cdp_session.assert_called_once_with(new)


def test_closed_popup_does_not_prevent_return_to_surviving_tab():
    instance = browser.Browser.__new__(browser.Browser)
    old = Mock(is_closed=Mock(return_value=True))
    survivor = Mock(is_closed=Mock(return_value=False))
    instance.page = old
    instance.session = Mock(detach=Mock(side_effect=RuntimeError('Target already closed')))
    instance.context = Mock(pages=[survivor])
    instance._adopt_latest_page()
    assert instance.page is survivor


def test_back_uses_only_observed_history_and_rejects_changed_history():
    instance = browser.Browser.__new__(browser.Browser)
    instance._adopt_latest_page = Mock()
    instance.evaluate = Mock(return_value=["same page"])
    history = {"currentIndex": 1, "entries": [
        {"id": 10, "url": "https://search.test", "title": "Search"},
        {"id": 11, "url": "https://source.test", "title": "Source"},
    ]}
    instance.call = Mock(return_value=history)
    action = instance.back_action()
    assert action["entry_id"] == 10
    assert instance.fresh({"marker": ["same page"]}, action)
    history["currentIndex"] = 0
    assert not instance.fresh({"marker": ["same page"]}, action)
    assert instance.back_action() is None


def test_switching_to_owned_tab_does_not_immediately_re_adopt_popup():
    instance = browser.Browser.__new__(browser.Browser)
    first = Mock(is_closed=Mock(return_value=False), url="https://first.test")
    popup = Mock(is_closed=Mock(return_value=False), url="https://jobs.test")
    instance.page = popup
    instance.known_pages = {first, popup}
    instance.context = Mock(pages=[first, popup])
    instance.session = Mock()
    instance.evaluate = Mock(return_value=["same"])
    action = instance.tab_action()
    assert action["tab_id"] == id(first)
    instance.act(action, {"marker": ["same"]})
    instance._adopt_latest_page()
    assert instance.page is first
    first.bring_to_front.assert_called_once()
    assert instance.tab_action()["tab_id"] == id(popup)


def test_closed_tab_cannot_be_selected_from_old_observation():
    instance = browser.Browser.__new__(browser.Browser)
    first = Mock(is_closed=Mock(return_value=False), url="https://first.test")
    popup = Mock(is_closed=Mock(return_value=False), url="https://jobs.test")
    instance.page = popup
    instance.known_pages = {first, popup}
    instance.context = Mock(pages=[first, popup])
    action = instance.tab_action()
    first.is_closed.return_value = True
    with pytest.raises(browser.BeforeActionStale):
        instance.act(action, {"marker": ["same"]})
    first.bring_to_front.assert_not_called()
