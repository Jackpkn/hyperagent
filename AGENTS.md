# HyperAgent

Read README.md before editing. Dual system: the System 2 LLM planner picks one tool per step and may `delegate`
on-page work to System 1 (TypeSafe Jev: one request picks an operation plus a typed target; a text helper writes
the value only for TYPE_TEXT). Every action: observe → decide → (approval) → execute → stream.

- The input is one natural-language goal. No site-specific plans, hardcoded flows or example goals anywhere: the agent must handle whatever the operator types.
- Jev consumes only the selected operation's target head; validate its answers before executing anything.
- The model addresses elements by the `[id]` of the latest observation. Never let it emit selectors or code.
- Model-chosen navigation is http(s) only. Credentials and API keys stay server-side; `.env` is ignored.
- Never retry a browser mutation automatically. Model calls may be retried; actions may not.
- Every failure must become a visible step error or notice. No silent failures; every run ends with a `result` and a terminal `status`.
- Pausing or new guidance discards an in-flight decision before it executes.
- Risky actions (submit, buy, send, delete…) wait for approval in the default mode.
- Keep docs/protocol.md, the UI types (apps/web/src/lib/protocol.ts) and the server events in sync.
- Tests must not call paid APIs. `tools/run_task.py` is the explicit live smoke runner.
- Do not commit or push unless the user requests it.

Checks: `uv run ruff check .`, `uv run pytest`, and `npm run lint && npm run typecheck && npm run build` in apps/web.
