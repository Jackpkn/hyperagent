from types import SimpleNamespace

import anthropic
import httpx
import pytest

from hyperagent.anthropic_backend import AnthropicBackend, AnthropicError, convert_messages, convert_tools, cost
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
                        reply(block(type="tool_use", name="navigate", input={"url": "https://x.test"}))])
    name, args, tokens_in, _, spent = await b.decide("claude-haiku-5-5", [{"role": "user", "content": "go"}], TOOLS)
    assert (name, args, tokens_in) == ("navigate", {"url": "https://x.test"}, 1000)
    assert spent == pytest.approx(0.00015)
    first = calls.calls[0]
    assert first["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert first["output_config"] == {"effort": "low"}
    assert calls.calls[1]["messages"][-1]["content"][0]["text"].startswith("Call exactly one tool")


async def test_forced_done_is_an_instruction_and_credit_errors_are_clear():
    b, calls = backend([reply(block(type="tool_use", name="done", input={"success": False}))])
    name, *_ = await b.decide("claude-sonnet-5-5", [{"role": "user", "content": "x"}], TOOLS, force="done")
    assert name == "done" and calls.calls[0]["output_config"] == {"effort": "low"}
    assert "Call the `done` tool now." in str(calls.calls[0]["messages"][-1]["content"])
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.BadRequestError("Your credit balance is too low", response=httpx.Response(400, request=request),
                                      body=None)
    b, _ = backend([error])
    with pytest.raises(AnthropicError, match="out of credit"):
        await b.decide("claude-haiku-5-5", [{"role": "user", "content": "x"}], TOOLS)
