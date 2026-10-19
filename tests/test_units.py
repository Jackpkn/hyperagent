import json
import re

import httpx
import pytest

from hyperagent.llm import LLMClient, LLMConfig, LLMError, parse_decision
from hyperagent.server import Command, origin_allowed
from hyperagent.tools import TOOLS, label, missing_args, needs_approval


def test_risk_policy():
    assert needs_approval("click", {}, "Submit order", "risky")[0]
    assert needs_approval("click", {"irreversible": True}, "Next", "risky")[0]
    assert not needs_approval("click", {}, "Next page", "risky")[0]
    assert not needs_approval("record_findings", {}, "", "always")[0]
    assert needs_approval("navigate", {}, "", "always")[0]
    assert not needs_approval("click", {"irreversible": True}, "Buy now", "never")[0]


def test_labels_are_plain_language():
    assert label("type_text", {"text": "pizza", "press_enter": True}, "Search") == \
        'Type "pizza" into "Search" and press Enter'
    assert label("record_findings", {"items": [{}, {}]}) == "Save 2 findings"


def test_every_tool_requires_public_reasoning():
    for tool in TOOLS:
        required = set(tool["function"]["parameters"]["required"])
        assert {"evaluation", "memory", "message"} <= required and "think" not in required
    assert missing_args("navigate", {"url": ""}) == ["url"]
    assert missing_args("click", {"element_id": 0}) == []
    # Clearing a field and an unfiltered extract are deliberate empty strings.
    assert missing_args("type_text", {"element_id": 1, "text": "", "press_enter": False}) == []
    assert missing_args("extract", {"fields": ["title"], "instruction": ""}) == []


def test_planner_thinks_only_on_hard_turns(monkeypatch):
    from hyperagent.anthropic_backend import speed_settings

    monkeypatch.delenv("PLANNER_THINKING", raising=False)
    monkeypatch.delenv("PLANNER_EFFORT", raising=False)
    assert speed_settings("claude-haiku-5-5", hard=False) == {"thinking": {"type": "disabled"}}
    assert speed_settings("claude-haiku-5-5", hard=True)["thinking"]["type"] == "adaptive"
    monkeypatch.setenv("PLANNER_THINKING", "1")
    assert speed_settings("claude-haiku-5-5", hard=False)["thinking"]["type"] == "adaptive"
    monkeypatch.setenv("PLANNER_THINKING", "0")
    assert speed_settings("claude-haiku-5-5", hard=True) == {"thinking": {"type": "disabled"}}


def tool_reply(name, args, cost=0.002):
    return {"choices": [{"message": {"tool_calls": [{"function": {"name": name, "arguments": json.dumps(args)}}]}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": cost}}


def test_parse_decision():
    d = parse_decision(tool_reply("click", {"element_id": 3}))
    assert (d.name, d.args, d.input_tokens, d.cost_usd) == ("click", {"element_id": 3}, 100, 0.002)
    with pytest.raises(LLMError):
        parse_decision({"choices": [{"message": {"content": "hello"}}]})


async def test_llm_retries_transient_errors_and_surfaces_auth_errors(monkeypatch):
    monkeypatch.setattr("hyperagent.llm.asyncio.sleep", _no_sleep)
    replies = iter([httpx.Response(503, text="busy"), httpx.Response(200, json=tool_reply("done", {}))])
    retries = []

    async def on_retry(message):
        retries.append(message)

    client = LLMClient(LLMConfig("http://llm.test", "k", ("m",)),
                       transport=httpx.MockTransport(lambda request: next(replies)))
    assert (await client.decide("m", [], [], on_retry=on_retry)).name == "done"
    assert len(retries) == 1
    client = LLMClient(LLMConfig("http://llm.test", "k", ("m",)),
                       transport=httpx.MockTransport(lambda request: httpx.Response(401)))
    with pytest.raises(LLMError, match="rejected the API key"):
        await client.decide("m", [], [])
    with pytest.raises(LLMError, match="No model API key"):
        await LLMClient(LLMConfig("http://llm.test", "", ("m",))).decide("m", [], [])


async def _no_sleep(_):
    return None


def test_origin_policy(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://console.example")
    assert origin_allowed("https://agent.up.railway.app", "agent.up.railway.app")
    assert origin_allowed("https://console.example", "api.example")
    assert origin_allowed("http://localhost:3000", "localhost:8766")
    assert not origin_allowed("https://evil.example", "agent.up.railway.app")


def test_commands_are_validated():
    assert Command.model_validate({"type": "start", "goal": " find x "}).goal == "find x"
    with pytest.raises(ValueError):
        Command.model_validate({"type": "rm -rf"})
    with pytest.raises(ValueError):
        Command.model_validate({"type": "start", "approval_mode": "yolo"})


def test_internal_hosts_are_not_public():
    from hyperagent.browser import _host_is_public
    for host in ("localhost", "127.0.0.1", "169.254.169.254", "10.0.0.5", "[::1]", "api.railway.internal"):
        assert not _host_is_public(host), host
    assert _host_is_public("93.184.215.14")


def test_action_parameters_precede_the_plan():
    for tool in TOOLS:
        keys = list(tool["function"]["parameters"]["properties"])
        assert keys[-1] == "plan" and keys[:4] == ["evaluation", "memory", "think", "message"], keys


async def test_text_only_models_get_screenshots_stripped():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        has_image = any(isinstance(m["content"], list) and any(p["type"] == "image_url" for p in m["content"])
                        for m in body["messages"])
        seen.append(has_image)
        if has_image:
            return httpx.Response(404, json={"error": {"message": "No endpoints found that support image input"}})
        return httpx.Response(200, json=tool_reply("done", {}))

    client = LLMClient(LLMConfig("http://llm.test", "k", ("m",)), transport=httpx.MockTransport(handler))
    messages = [{"role": "user", "content": [{"type": "text", "text": "hi"},
                                             {"type": "image_url", "image_url": {"url": "data:x"}}]}]
    assert (await client.decide("m", messages, [])).name == "done"
    assert (await client.decide("m", messages, [])).name == "done"
    assert seen == [True, False, False], "only the first request carries the image"


def test_native_date_and_time_values_are_normalized():
    from hyperagent.browser import normalize_native
    assert normalize_native("date", "10/17/2026") == "2026-10-17"
    assert normalize_native("date", "October 17, 2026") == "2026-10-17"
    assert normalize_native("time", "7:30 PM") == "19:30"
    assert normalize_native("time", "19:30") == "19:30"
    assert normalize_native("date", "next friday") == "next friday"


def test_bot_wall_ignores_recaptcha_footer():
    from hyperagent.agent import _page_warnings
    from hyperagent.browser import Observation
    obs = Observation(
        url="https://booking.test/checkout",
        title="Checkout",
        text="Complete your booking. Protected by reCAPTCHA - Privacy - Terms",
        truncated=False,
        elements={1: {"id": 1, "tag": "button", "label": "Book"}},
        scroll={"y": 0, "viewport": 800, "height": 800, "width": 1280},
        tabs=[],
    )
    assert _page_warnings(obs) == []


def test_grounded_field_verification_checks_page_corpus():
    from hyperagent.agent import _verify_field
    corpus = "Wayfair Accent Chair $219.00 — Rating 4.3 out of 5 — Ships by 2026-10-22"
    assert _verify_field("$219", corpus)
    assert _verify_field("Wayfair Accent Chair", corpus)
    assert _verify_field("not_found", corpus)
    assert _verify_field("(empty)", corpus)  # a blank form field echoed back is not a claim to check
    assert _verify_field("https://wayfair.com/p/1", corpus)
    assert not _verify_field("$999.00", corpus)
    assert not _verify_field("Completely Hallucinated Product", corpus)




def test_tool_schemas_stay_compact():
    # The tool list is resent on every planner call; shared reasoning fields are described once in the
    # system prompt, not copied into every tool.
    import json

    from hyperagent.tools import TOOLS_WITH_FAST
    assert len(json.dumps(TOOLS_WITH_FAST)) < 18000
    delegate = next(t for t in TOOLS_WITH_FAST if t["function"]["name"] == "delegate")
    assert "description" not in delegate["function"]["parameters"]["properties"]["memory"]


def test_start_command_bounds_conversation_and_memory():
    import pytest
    from pydantic import ValidationError

    from hyperagent.server import Command
    cmd = Command.model_validate({"type": "start", "goal": "Sort them", "user_memory": ["Prices in INR"],
                                  "conversation": [{"goal": "Find books", "answer": "Five qualify.",
                                                    "columns": ["title"], "rows": [{"title": "Thirst"}]}]})
    assert cmd.conversation[0].rows == [{"title": "Thirst"}] and cmd.user_memory == ["Prices in INR"]
    with pytest.raises(ValidationError):
        Command.model_validate({"type": "start", "goal": "x", "user_memory": ["m" * 300]})
    with pytest.raises(ValidationError):
        Command.model_validate({"type": "start", "goal": "x", "conversation": [{"goal": "g"}] * 13})


def test_compact_page_text_keeps_values_states_and_links():
    from hyperagent.prompts import compact_page_text

    text = ('Flights\n[15]<input role=combobox type=text value="Jaipur" expanded=false>Where from?</input>\n'
            '[23]<button role=tab selected=true>Jaipur</button>  [24]<button disabled>Swap</button>\n'
            '[30]<a href="/next/2">Next page</a> (below)\n'
            '[31]<div role=link>' + "From 12765 Indian rupees. Nonstop flight with SpiceJet. " * 3 + '</div>\n'
            '[32]<input type=password empty>Password</input>\n'
            '[33]<input type=checkbox checked>Nonstop only</input>')
    out = compact_page_text(text)
    assert "[Where from? =\"Jaipur\"]" in out and "[Jaipur · selected]" in out and "[Swap · disabled]" in out
    assert "[Next page](/next/2) (below)" in out and "[Password · empty]" in out and "[Nonstop only · checked]" in out
    assert "From 12765 Indian rupees" in out and len(out.split("\n")[4]) <= 62
    assert not re.search(r"\[\d+\]<", out)


@pytest.mark.parametrize("label", ["Sorted by top flights, Change sort order.", "Apply filters", "Places to visit",
                                   "Price", "Nonstop only"])
def test_everyday_controls_do_not_ask_for_approval(label):
    assert needs_approval("click", {}, label, "risky") == (False, "")
    assert needs_approval("delegate", {"subgoal": f'Click "{label}"'}, "", "risky") == (False, "")


@pytest.mark.parametrize("label", ["Place order", "Buy now", "Pay ₹12,765", "Proceed to checkout", "Book",
                                   "Submit", "Delete account", "Purchase Flight", "Confirm booking"])
def test_committing_controls_still_ask_for_approval(label):
    assert needs_approval("click", {}, label, "risky")[0]


def test_long_conversation_keeps_the_newest_turn_for_follow_ups():
    from hyperagent.prompts import _conversation_block

    older = [{"goal": f"Old question {i}", "answer": "x" * 1500} for i in range(8)]
    newest = {"goal": "List invoices over $500", "answer": "Twelve invoices qualify.", "columns": ["invoice", "amount"],
              "rows": [{"invoice": f"INV-{i}", "amount": "$" + "9" * 280, "note": "n" * 280}
                       for i in range(20)]}
    block = _conversation_block([*older, newest])
    assert len(block) <= 8200
    assert "List invoices over $500" in block and "INV-0" in block  # what "sort those" refers to survives
    assert "Old question 0" not in block and "earlier turns omitted" in block
    assert "rows_omitted" in block
    for line in block.splitlines()[2:-1]:
        json.loads(line)  # never cut mid-value


def test_findings_context_shows_the_newest_rows():
    from hyperagent.prompts import _findings_block

    findings = [{"vendor": f"Vendor {i}", "note": "n" * 400} for i in range(40)]
    block = _findings_block(findings)
    assert 'count="40"' in block and "Vendor 39" in block and "Vendor 0\"" not in block
    assert "earlier rows not shown" in block
