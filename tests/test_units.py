import json

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
        assert {"evaluation", "memory", "next_goal"} <= set(tool["function"]["parameters"]["required"])
    assert missing_args("navigate", {"url": ""}) == ["url"]
    assert missing_args("click", {"element_id": 0}) == []


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
        assert keys[-1] == "plan" and keys[:3] == ["evaluation", "memory", "next_goal"], keys


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
    assert _verify_field("https://wayfair.com/p/1", corpus)
    assert not _verify_field("$999.00", corpus)
    assert not _verify_field("Completely Hallucinated Product", corpus)




def test_tool_schemas_stay_compact():
    # The tool list is resent on every planner call; shared reasoning fields are described once in the
    # system prompt, not copied into every tool.
    import json

    from hyperagent.tools import TOOLS_WITH_FAST
    assert len(json.dumps(TOOLS_WITH_FAST)) < 18000
    click = next(t for t in TOOLS_WITH_FAST if t["function"]["name"] == "click")
    assert "description" not in click["function"]["parameters"]["properties"]["memory"]


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
