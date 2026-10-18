"""Run one goal headlessly against the real agent and print the timeline. Uses paid model calls."""

import argparse
import asyncio
import json
import math
import time
from pathlib import Path

from hyperagent.agent import Agent
from hyperagent.browser import BrowserSession
from hyperagent.fast import FastConfig, FastPolicy
from hyperagent.llm import LLMClient, LLMConfig


def positive_number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return number


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("goal", nargs="?")
    parser.add_argument("--url")
    parser.add_argument("--model")
    parser.add_argument("--mode", choices=["risky", "always", "never"],
                        help="default: never for ordinary smoke runs, risky for eval cases")
    parser.add_argument("--approve", action="store_true", help="auto-approve risky steps (for unattended runs)")
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--out", default="")
    parser.add_argument("--no-fast", action="store_true", help="disable the Jev System 1 policy")
    parser.add_argument("--timezone", default=None, help="operator IANA time zone, e.g. Europe/London")
    parser.add_argument("--conversation", default="", help="JSON file of earlier chat turns "
                        "([{goal, answer, columns?, rows?}]) to test follow-up questions")
    parser.add_argument("--memory", action="append", default=[], help="a long-term memory item (repeatable)")
    parser.add_argument("--eval-case", choices=["prefilled-form", "autocomplete"],
                        help="run an independently graded fixture; uses paid models, requires --out")
    parser.add_argument("--timeout", type=positive_number, default=120,
                        help="eval only: maximum agent run seconds (default 120)")
    parser.add_argument("--max-cost", type=positive_number, default=0.25,
                        help="eval only: planner/extraction cost limit; excludes Jev/text helper and may overshoot")
    args = parser.parse_args()
    if args.max_steps <= 0:
        parser.error("--max-steps must be positive")
    if args.eval_case:
        if not args.out:
            parser.error("--eval-case requires --out to preserve evidence")
        if args.goal or args.url or args.conversation or args.memory or args.approve:
            parser.error("eval cases supply their own goal and clean state; "
                         "goal/URL/history/auto-approval are unsupported")
        if Path(args.out).exists():
            parser.error("choose a new --out path; existing eval evidence is never overwritten")
        if __package__:
            from .evals.runner import run_case
        else:
            from evals.runner import run_case
        raise SystemExit(await run_case(args))
    if not args.goal:
        parser.error("provide a goal or --eval-case")
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
    await browser.start(args.url or "https://www.bing.com/")
    agent = Agent(browser=browser, llm=llm, emit=emit, goal=args.goal, model=args.model or config.default_model,
                  approval_mode=args.mode or "never", max_steps=args.max_steps, fast=fast, timezone=args.timezone,
                  conversation=json.loads(Path(args.conversation).read_text()) if args.conversation else None,
                  user_memory=args.memory)
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


if __name__ == "__main__":
    asyncio.run(main())
