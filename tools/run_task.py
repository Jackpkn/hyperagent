"""Run one goal headlessly against the real agent and print the timeline. Uses paid model calls."""

import argparse
import asyncio
import json
import time
from pathlib import Path

from hyperagent.agent import Agent
from hyperagent.browser import BrowserSession
from hyperagent.fast import FastConfig, FastPolicy
from hyperagent.llm import LLMClient, LLMConfig


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("goal")
    parser.add_argument("--url", default="https://www.bing.com/")
    parser.add_argument("--model")
    parser.add_argument("--mode", default="never", choices=["risky", "always", "never"])
    parser.add_argument("--approve", action="store_true", help="auto-approve risky steps (for unattended runs)")
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--out", default="")
    parser.add_argument("--no-fast", action="store_true", help="disable the Jev System 1 policy")
    parser.add_argument("--timezone", default=None, help="operator IANA time zone, e.g. Europe/London")
    args = parser.parse_args()
    config = LLMConfig.from_env()
    llm = LLMClient(config)
    events: list[dict] = []
    agent: Agent | None = None
    started = time.time()

    async def emit(event: dict) -> None:
        events.append({"t": round(time.time() - started, 2), **event})
        kind = event["type"]
        if kind == "step" and event["status"] in ("ok", "error", "rejected", "skipped"):
            outcome = event.get("error") or event.get("result")
            tag = "jev" if event.get("system") == "fast" else "s2 "
            conf = ""
            if event.get("confidence") is not None:
                conf = f" ({event['confidence']:.0%}, {event.get('latency_ms')} ms)"
            print(f"[{time.time() - started:6.1f}s] {tag} #{event['n']} {event['status']:8}{conf} "
                  f"{event.get('action', {}).get('label', '')} → {outcome}", flush=True)
            if event.get("thought") and event.get("system") != "fast":
                print(f"           why: {event['thought'].get('next_goal')}")
        elif kind == "notice":
            print(f"           ({event['level']}) {event['message']}", flush=True)
        elif kind == "question" and agent:
            print(f"           (question for the operator) {event['question']}", flush=True)
            print("           (unattended run) nobody can answer; stopping.", flush=True)
            await agent.stop()
        elif kind == "status" and event["state"] == "paused" and agent:
            print("           (unattended run) the agent paused for a person; stopping.", flush=True)
            await agent.stop()
        elif kind == "approval" and args.approve and agent:
            print(f"           auto-approving: {event['action_label']}")
            agent.resolve_approval(event["step_id"], True)

    fast_config = FastConfig.from_env()
    fast = FastPolicy(fast_config) if fast_config.enabled and not args.no_fast else None
    browser = BrowserSession()
    await browser.start(args.url)
    agent = Agent(browser=browser, llm=llm, emit=emit, goal=args.goal, model=args.model or config.default_model,
                  approval_mode=args.mode, max_steps=args.max_steps, fast=fast, timezone=args.timezone)
    try:
        result = await agent.run()
    finally:
        await browser.close()
        await llm.close()
        if fast:
            await fast.close()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(agent.usage), f"{time.time() - started:.1f}s")
    if args.out:
        Path(args.out).write_text(json.dumps({"goal": args.goal, "result": result, "usage": agent.usage,
                                              "events": [e for e in events if e["type"] != "frame"]}, indent=1))


asyncio.run(main())
