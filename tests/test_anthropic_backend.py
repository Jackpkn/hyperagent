from types import SimpleNamespace

import anthropic
import httpx
import pytest

from hyperagent.anthropic_backend import (
    AnthropicBackend,
    AnthropicError,
    _recover_xml_params,
    convert_messages,
    convert_tools,
    cost,
    extract_partial_thought,
)
from hyperagent.tools import TOOLS


def block(**kw):
    return SimpleNamespace(**kw, model_dump=lambda exclude_none=True: {"type": kw["type"], "text": kw.get("text")})


def reply(*blocks, stop="tool_use"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=1000, output_tokens=100))


class FakeMessages:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def backend(replies):
    fake = SimpleNamespace(messages=FakeMessages(replies), close=None)
    return AnthropicBackend("k", client=fake), fake.messages


def test_message_and_tool_conversion():
    system, msgs = convert_messages([
        {"role": "system", "content": "rules"},
        {"role": "user", "content": [{"type": "text", "text": "page"},
                                     {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}}]},
    ])
    assert system == "rules"
    assert msgs[0]["content"][0] == {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                                  "data": "QUJD"}}
    tools = convert_tools(TOOLS)
    assert tools[0]["name"] == "search" and "input_schema" in tools[0]
    assert cost("claude-haiku-5-5", 1_000_000, 0) == pytest.approx(0.10)


async def test_decide_uses_auto_tool_choice_and_retries_without_tool_call():
    b, calls = backend([reply(block(type="text", text="thinking aloud"), stop="end_turn"),
                        reply(block(type="thinking", thinking="Need to open x.test first."),
                              block(type="tool_use", name="navigate", input={"url": "https://x.test"}))])
    name, args, tokens_in, _, spent, _ = await b.decide("claude-haiku-5-5", [{"role": "user", "content": "go"}], TOOLS)
    assert (name, args, tokens_in) == (
        "navigate",
        {"url": "https://x.test", "_thinking": "Need to open x.test first."},
        1000,
    )
    assert spent == pytest.approx(0.00015)
    first = calls.calls[0]
    assert first["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert first["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert first["output_config"] == {"effort": "medium"}
    assert calls.calls[1]["messages"][-1]["content"][0]["text"].startswith("Call exactly one tool")


async def test_forced_done_is_an_instruction_and_credit_errors_are_clear():
    b, calls = backend([reply(block(type="tool_use", name="done", input={"success": False}))])
    name, *_ = await b.decide("claude-sonnet-5-5", [{"role": "user", "content": "x"}], TOOLS, force="done")
    assert name == "done" and calls.calls[0]["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert "Call the `done` tool now." in str(calls.calls[0]["messages"][-1]["content"])
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.BadRequestError("Your credit balance is too low", response=httpx.Response(400, request=request),
                                      body=None)
    b, _ = backend([error])
    with pytest.raises(AnthropicError, match="out of credit"):
        await b.decide("claude-haiku-5-5", [{"role": "user", "content": "x"}], TOOLS)


async def test_reply_cut_off_at_the_output_limit_is_never_acted_on():
    cut = reply(block(type="tool_use", name="done", input={"success": True, "rows": [{"a": "1"}]}), stop="max_tokens")
    full = reply(block(type="tool_use", name="done", input={"success": True, "rows": [{"a": "1"}, {"a": "2"}]}))
    b, calls = backend([cut, full])
    name, args, *_ = await b.decide("claude-haiku-5-5", [{"role": "user", "content": "x"}], TOOLS)
    assert name == "done" and args["rows"] == [{"a": "1"}, {"a": "2"}]  # the half table was never used
    assert calls.calls[0]["max_tokens"] >= 16000
    assert "output limit" in str(calls.calls[1]["messages"][-1]["content"])
    assert "output limit" not in str(calls.calls[0]["messages"][-1]["content"])  # the first request is untouched


def test_recover_xml_params_and_extract_partial_thought():
    leaked = {
        "evaluation": (
            'Page 1 of Historical Fiction is read and saved.</evaluation> '
            '<parameter name="memory">Science top 2 saved.</parameter> '
            '<parameter name="next_goal">Open page 2 of Historical Fiction.</parameter> '
            '<parameter name="element_id">115'
        )
    }
    recovered = _recover_xml_params(leaked)
    assert recovered["evaluation"] == "Page 1 of Historical Fiction is read and saved."
    assert recovered["memory"] == "Science top 2 saved."
    assert recovered["next_goal"] == "Open page 2 of Historical Fiction."
    assert recovered["element_id"] == 115

    partial = '{"evaluation": "Scanning 14 books on page 1", "next_goal": "Click next'
    thought = extract_partial_thought(partial)
    assert thought["evaluation"] == "Scanning 14 books on page 1"
    assert thought["next_goal"] == "Click next"



async def test_static_system_prompt_and_tools_are_cached_and_cache_tokens_are_billed():
    usage = SimpleNamespace(input_tokens=1000, output_tokens=100, cache_creation_input_tokens=2000,
                            cache_read_input_tokens=10000)
    tool = block(type="tool_use", name="wait", input={"seconds": 1})
    b, calls = backend([SimpleNamespace(content=[tool], stop_reason="tool_use", usage=usage)])
    _, _, tokens_in, _, spent, cached = await b.decide(
        "claude-haiku-5-5", [{"role": "system", "content": "rules"}, {"role": "user", "content": "page"}], TOOLS)
    assert calls.calls[0]["system"] == [{"type": "text", "text": "rules", "cache_control": {"type": "ephemeral"}}]
    assert tokens_in == 13000 and cached == 10000
    expected = (1000 * 0.10 + 2000 * 0.10 * 1.25 + 10000 * 0.10 * 0.1 + 100 * 0.50) / 1_000_000
    assert spent == pytest.approx(expected)


def test_partial_stream_surfaces_the_narration_message():
    partial = '{"evaluation": "Page loaded", "memory": "m", "next_goal": "Open Fiction", "message": "Found the Fic'
    assert extract_partial_thought(partial)["message"] == "Found the Fic"
