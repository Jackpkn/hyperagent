"""Direct Anthropic (Claude API) backend for the planner and the text helper, via the official SDK."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import anthropic

# USD per million tokens (input, output), Claude API first-party rates.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


class AnthropicError(RuntimeError):
    """Raised with an operator-safe message; nothing was executed."""


def convert_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """OpenAI-style chat messages (as the agent builds them) → Anthropic system + messages."""
    system_parts, out = [], []
    for m in messages:
        content = m.get("content")
        if m["role"] == "system":
            system_parts.append(content if isinstance(content, str) else json.dumps(content))
            continue
        if isinstance(content, str):
            blocks: list[dict[str, Any]] = [{"type": "text", "text": content}]
        else:
            blocks = []
            for part in content or []:
                if part.get("type") == "text":
                    blocks.append({"type": "text", "text": part["text"]})
                elif part.get("type") == "image_url":
                    url = part["image_url"]["url"]
                    header, _, data = url.partition(",")
                    media = header.removeprefix("data:").split(";")[0] or "image/jpeg"
                    blocks.insert(0, {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
        if out and out[-1]["role"] == m["role"]:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": m["role"], "content": blocks})
    return "\n\n".join(system_parts), out


def convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"name": t["function"]["name"], "description": t["function"]["description"],
             "input_schema": t["function"]["parameters"]} for t in tools]


def speed_settings(model: str) -> dict[str, Any]:
    """Each decision is one small step: keep latency low without breaking per-model thinking rules."""
    if model.startswith("claude-haiku") and os.environ.get("PLANNER_THINKING", "1") == "0":
        return {"thinking": {"type": "disabled"}}
    return {"output_config": {"effort": "low"}}


def cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


class AnthropicBackend:
    def __init__(self, api_key: str, client: Any = None):
        # The agent reports each retry to the operator, so the SDK's silent retries are turned off.
        self.client = client or anthropic.AsyncAnthropic(api_key=api_key, max_retries=0, timeout=90)

    async def decide(self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *,
                     force: str | None = None, on_retry: Any = None) -> tuple[str, dict[str, Any], int, int, float]:
        system, converted = convert_messages(messages)
        if force:
            # Forced tool_choice is rejected on current models; instruct instead and verify the result.
            converted[-1]["content"].append({"type": "text", "text": f"Call the `{force}` tool now."})
        last = "unknown error"
        wait = 0.0
        for attempt in range(5):
            try:
                response = await self.client.messages.create(
                    model=model, max_tokens=4096, system=system, messages=converted, tools=convert_tools(tools),
                    tool_choice={"type": "auto", "disable_parallel_tool_use": True}, **speed_settings(model),
                )
            except anthropic.AuthenticationError:
                raise AnthropicError("Anthropic rejected the API key.") from None
            except anthropic.PermissionDeniedError:
                raise AnthropicError("This Anthropic API key may not use that model.") from None
            except anthropic.NotFoundError:
                raise AnthropicError(f"Anthropic does not know the model {model!r}.") from None
            except anthropic.BadRequestError as exc:
                message = str(getattr(exc, "message", exc))
                if "credit" in message.lower():
                    raise AnthropicError("The Anthropic account is out of credit.") from None
                raise AnthropicError(f"Anthropic refused the request: {message[:200]}") from None
            except anthropic.RateLimitError as exc:
                last = "rate limited"
                retry_after = exc.response.headers.get("retry-after") if exc.response is not None else None
                wait = min(float(retry_after), 30.0) if retry_after and retry_after.replace(".", "").isdigit() else 0
            except anthropic.APIStatusError as exc:
                last = f"HTTP {exc.status_code}"
            except anthropic.APIConnectionError:
                last = "connection error"
            else:
                if response.stop_reason == "refusal":
                    raise AnthropicError("Claude declined this step for safety reasons.")
                usage = response.usage
                spent = cost(model, usage.input_tokens, usage.output_tokens)
                call = next((b for b in response.content if b.type == "tool_use"), None)
                if call is not None and (not force or call.name == force):
                    return call.name, dict(call.input), usage.input_tokens, usage.output_tokens, spent
                last = "the reply did not choose an action"
                converted = [*converted,
                             {"role": "assistant", "content": [b.model_dump(exclude_none=True)
                                                               for b in response.content if b.type == "text"]
                              or [{"type": "text", "text": "(no action)"}]},
                             {"role": "user", "content": [{"type": "text", "text": "Call exactly one tool"
                                                           + (f" (`{force}`)" if force else "") + " now."}]}]
                continue
            if attempt < 4:
                delay = max(wait, 2.0 * 2**attempt)
                wait = 0.0
                if on_retry:
                    await on_retry(f"Model call failed ({last}); retrying in {delay:.0f} s ({attempt + 1}/4)…")
                await asyncio.sleep(delay)
        raise AnthropicError(f"Claude did not respond after 5 attempts: {last}")

    async def complete_json(self, model: str, system: str, user: str) -> tuple[dict[str, Any], int, int]:
        """One small JSON answer (used by the text helper)."""
        try:
            response = await self.client.messages.create(
                model=model, max_tokens=400, system=system, messages=[{"role": "user", "content": user}],
                **speed_settings(model),
            )
        except anthropic.APIError as exc:
            raise AnthropicError(f"The text helper failed: {type(exc).__name__}") from None
        text = "".join(b.text for b in response.content if b.type == "text")
        try:
            return json.loads(text[text.find("{"): text.rfind("}") + 1]), response.usage.input_tokens, \
                response.usage.output_tokens
        except ValueError:
            raise AnthropicError("The text helper did not return JSON.") from None

    async def close(self) -> None:
        await self.client.close()
