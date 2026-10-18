"""Single-trial live evaluator. Called explicitly by tools/run_task.py, never by the app."""

import asyncio
import hashlib
import json
import subprocess
import time
from pathlib import Path

from hyperagent.agent import Agent
from hyperagent.browser import BrowserSession
from hyperagent.fast import RULES, TEXT_RULES, FastConfig, FastPolicy
from hyperagent.llm import LLMClient, LLMConfig
from hyperagent.prompts import SYSTEM, SYSTEM_FAST
from hyperagent.tools import TOOLS, TOOLS_WITH_FAST

from .autocomplete import Autocomplete
from .prefilled_form import PrefilledForm

CASES = {case.id: case for case in (PrefilledForm, Autocomplete)}


def revision() -> dict:
    root = Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip())
        return {"commit": sha, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


async def run_case(args) -> int:
    """Return zero only for a finished run whose independent environment checks all pass."""
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the report before launching a browser or making any model request.
    with output.open("x") as stream:
        return await _run(args, stream)


async def _run(args, stream) -> int:
    started = time.monotonic()
    case, browser = CASES[args.eval_case](), BrowserSession()
    events, cleanup_errors = [], []
    agent, llm, fast, result = None, None, None, None
    terminal, error, cancellation = "error", None, None
    configuration = {"mode": "planner-only", "planner_model": None, "fast_model": None,
                     "approval_mode": args.mode or "risky", "max_steps": args.max_steps,
                     "timeout_s": args.timeout, "tracked_cost_limit_usd": args.max_cost}

    async def emit(event):
        if event["type"] == "frame":
            return
        events.append({"t": round(time.monotonic() - started, 3), **event})
        if event["type"] in {"question", "approval"} or (
                event["type"] == "status" and event["state"] == "paused"):
            if agent:
                await agent.stop()  # no unattended answers or blanket approvals

    try:
        config = LLMConfig.from_env()
        llm = LLMClient(config)
        fast_config = FastConfig.from_env()
        if not args.no_fast:
            if not fast_config.enabled:
                raise ValueError("Jev is not configured; use --no-fast for an explicitly planner-only trial.")
            fast = FastPolicy(fast_config)
        configuration.update(planner_model=args.model or config.default_model,
                             mode="planner+jev" if fast else "planner-only",
                             fast_model=fast_config.model if fast else None,
                             text_model=fast_config.text_model if fast else None)
        await browser.start("about:blank")
        await case.setup(browser)
        agent = Agent(browser=browser, llm=llm, fast=fast, emit=emit, goal=case.goal,
                      model=configuration["planner_model"], approval_mode=configuration["approval_mode"],
                      max_steps=args.max_steps, max_cost_usd=args.max_cost, vision=False)
        result = await asyncio.wait_for(agent.run(), timeout=args.timeout)
        terminal = "stopped" if agent.stopped else "done" if result.get("success") else "failed"
        await agent.set_state(terminal)
    except (Exception, asyncio.CancelledError) as exc:
        if isinstance(exc, asyncio.CancelledError):
            cancellation = exc
            terminal = "interrupted"
        else:
            terminal = "timeout" if isinstance(exc, TimeoutError) else "error"
        error = type(exc).__name__
        if agent:
            await agent.stop()
        result = {"type": "result", "success": False, "summary": f"Evaluation ended: {terminal} ({error}).",
                  "columns": [], "rows": [], "sources": [], "issues": [f"{terminal}: {error}"]}
        await emit(result)
        await emit({"type": "status", "state": "stopped" if terminal in {"timeout", "interrupted"} else "failed",
                    "step": agent.actions_taken if agent else 0, "detail": result["summary"]})
    finally:
        grading = await case.grade(browser) if browser.page and browser.context else {
            "passed": False, "checks": [], "evidence": {"observation_error": "Browser unavailable"}}
        for resource in (browser, fast, llm):
            if resource is not None:
                try:
                    await resource.close()
                except Exception as exc:
                    cleanup_errors.append(type(exc).__name__)

    steps = {e["id"]: e for e in events if e["type"] == "step"}
    mutations = {"click", "type_text", "select_option", "scroll", "press_key", "navigate", "go_back"}
    report = {
        "case": case.id, "case_version": case.version, "goal": case.goal, "revision": revision(),
        "configuration": configuration,
        "prompt_sha256": hashlib.sha256((SYSTEM + (SYSTEM_FAST + RULES + TEXT_RULES if fast else "")
                                         + json.dumps(TOOLS_WITH_FAST if fast else TOOLS)).encode()).hexdigest(),
        "fixture_sha256": hashlib.sha256(case.fixture_path.read_bytes()).hexdigest(),
        "passed": grading["passed"] and terminal == "done" and not cleanup_errors,
        "terminal": terminal, "error_type": error, "agent_claimed_success": (result or {}).get("success"),
        "grading": grading, "agent_result": result, "events": events,
        "elapsed_s": round(time.monotonic() - started, 3), "recorded_usage": agent.usage if agent else {},
        "executed_actions": sum(s.get("status") == "ok" and s.get("action", {}).get("name") in mutations
                                for s in steps.values()),
        "step_errors": sum(s.get("status") == "error" for s in steps.values()),
        "total_cost_usd": None,
        "usage_limitations": "Recorded tokens/cost cover planner and extraction only. Jev and text-helper costs "
                             "are missing, so total cost and token savings are unknown. Cost limit is checked "
                             "between planner steps and may be exceeded by an in-flight call.",
        "cleanup_errors": cleanup_errors,
    }
    json.dump(report, stream, indent=2)
    stream.write("\n")
    stream.flush()
    print(json.dumps({"case": case.id, "passed": report["passed"], "terminal": terminal,
                      "failed_checks": [c["id"] for c in grading["checks"] if not c["passed"]],
                      "elapsed_s": report["elapsed_s"], "report": args.out}))
    if cancellation is not None:
        raise cancellation
    return 0 if report["passed"] else 1
