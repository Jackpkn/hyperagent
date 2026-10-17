"""Run one bounded real browser task against a running service; never imported by pytest.

This uses the service's configured (potentially paid) providers. It records failed
attempts too, and never approves sensitive actions or retries browser mutations.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

import websockets


async def run(args):
    started = time.monotonic()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    events, frames, snapshots = [], 0, []
    terminal = "timeout"
    error_type = None
    try:
        async with websockets.connect(args.endpoint, origin=args.origin, max_size=25_000_000) as ws:
            command = {"command": "START", "goal": args.goal, "auto_run": True}
            if args.url:
                command["url"] = args.url
            await ws.send(json.dumps(command))
            try:
                while time.monotonic() - started < args.timeout:
                    remaining = args.timeout - (time.monotonic() - started)
                    try:
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=max(0.01, remaining)))
                    except TimeoutError:
                        break
                    if msg["type"] == "BROWSER_FRAME":
                        frames += 1
                        continue
                    msg["received_seconds"] = round(time.monotonic() - started, 3)
                    if msg["type"] == "STATE_SNAPSHOT":
                        msg["state"]["page"].pop("screenshot", None)
                        snapshots.append(msg["state"])
                    events.append(msg)
                    with (output / "events.jsonl").open("a") as stream:
                        stream.write(json.dumps(msg) + "\n")
                    if msg["type"] not in {"TASK_PROGRESS", "STATE_SNAPSHOT", "ACTIVITY", "TELEMETRY_TICK"}:
                        message = msg.get("reason") or msg.get("phase") or msg.get("message") or ""
                        print(msg["type"], message, flush=True)
                    if msg["type"] in {"MISSION_COMPLETE", "OUTCOME_UNVERIFIED", "HUMAN_APPROVAL_REQUIRED",
                                       "PAUSED", "BLOCKED", "ERROR"}:
                        terminal = msg["type"]
                        break
                    if msg["type"] == "STATE_SNAPSHOT" and msg.get("status") == "paused":
                        terminal = "PAUSED"
                        break
                    if snapshots and len(snapshots[-1]["history"]) >= args.max_actions:
                        terminal = "action_limit"
                        break
            finally:
                # Request orderly close; never replay the task on reconnect.
                try:
                    await ws.send(json.dumps({"command": "STOP"}))
                    async with asyncio.timeout(60):
                        while True:
                            msg = json.loads(await ws.recv())
                            if msg["type"] == "STATE_SNAPSHOT":
                                msg["state"]["page"].pop("screenshot", None)
                                snapshots.append(msg["state"])
                            if msg["type"] == "STOPPED":
                                break
                except (TimeoutError, OSError, websockets.WebSocketException):
                    pass
    except (OSError, TimeoutError, websockets.WebSocketException, ValueError) as exc:
        terminal = "transport_error"
        error_type = type(exc).__name__
    state = snapshots[-1] if snapshots else {}
    complete = next((event for event in events if event["type"] == "MISSION_COMPLETE"), None)
    result = {
        "goal": args.goal, "starting_url": args.url or "server default", "terminal_event": terminal,
        "verified": bool(complete and complete["deliverable"].get("verified")),
        "error_type": error_type,
        "elapsed_seconds": round(time.monotonic() - started, 3), "frames_received": frames,
        "browser_actions": len(state.get("history", [])), "policy_decisions": len(state.get("decisions", [])),
        "text_helper_decisions": len(state.get("text_calls", [])),
        "recovery_decisions": sum(event["type"] == "SYS2_RECOVERY_DECISION" for event in events),
        "visited_pages": list(dict.fromkeys(s["page"]["url"] for s in snapshots)),
        "limits": "One smoke run, not a reliability benchmark. Decision counts exclude HTTP retries. "
                  "Completion is model-verified; inspect the final source evidence independently.",
    }
    (output / "result.json").write_text(json.dumps(result, indent=2))
    if complete:
        (output / "deliverable.json").write_text(json.dumps(complete["deliverable"], indent=2))
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--url", help="Optional starting website; otherwise the server's search entry page is used")
    parser.add_argument("--endpoint", default="ws://127.0.0.1:8770/ws/agent")
    parser.add_argument("--origin", default="http://localhost:8770")
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--max-actions", type=int, default=40)
    parser.add_argument("--output", default=f"artifacts/benchmarks/{time.time_ns()}")
    args = parser.parse_args()
    if args.timeout <= 0 or args.max_actions <= 0:
        parser.error("timeout and max-actions must be positive")
    if (Path(args.output) / "events.jsonl").exists():
        parser.error("choose a new output directory so runs are never mixed")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
