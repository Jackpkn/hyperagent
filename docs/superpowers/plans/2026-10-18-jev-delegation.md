# Prefer complete Jev interaction sequences

User approved the proposed delegation fix after first committing existing work. Checkpoints are 1dbd4a2 (refresh persistence) and 2fe7882 (UI). The observed Google Flights run used 22 planner calls and zero fast calls despite Jev being configured.

## Scope and constraints

- This increment addresses planner bypass of Jev and premature handback on already-correct fields. Preserve frontend, existing event schemas, approvals, navigation restrictions, latest-observation IDs, user interruption, no automatic mutation retries, and planner-only operation when Jev is unavailable.
- No site-specific rules, new dependencies, new automatic pause/cycle system, model/config changes, or paid calls in tests. No new commits or pushes in this implementation phase; leave the change reviewable after the checkpoints.
- Do not convert a planner-chosen click into an additional one-action Jev call. Avoid the planner decision in the first place by offering delegation for ordinary UI work.
- Do not claim a general completion verifier: Jev's done remains a claim that the planner checks against the current page before extracting/comparing/reporting. Keep actual input/control state in Jev's observations and skip log so it can progress without another planner turn.

## Task 1: Route normal UI sequences to Jev, preserve recovery

Allowed product files: hyperagent/agent.py, hyperagent/system1.py, hyperagent/tools.py, hyperagent/prompts.py, hyperagent/fast.py only if needed for skip context. Tests in tests/test_system1.py, tests/test_agent.py, tests/test_units.py, tests/fakes.py, or focused new test files. Documentation README.md and docs/protocol.md only to describe actual behavior; no protocol type/event changes.

1. When Jev is configured, normal planner tool selection offers delegate instead of routine click/type_text/select_option/scroll. Keep navigation, read/extract/record, questions, keyboard-only operations, tab operations and final result available. Password typing remains possible directly with existing mandatory approval; do not expose ordinary type_text as an unrestricted escape hatch.
2. Enforce the selected mode at execution too: an unoffered direct routine action must produce a visible error and no mutation, rather than bypassing the routing policy. Password restrictions must be based on the observed element, never a model assertion.
3. After an actual Jev inability to proceed (error, stuck, low confidence, unchanged-state limit, action budget), permit one planner recovery decision using direct UI tools on a fresh observation, then restore normal delegation. No recovery permission on successful completion, approval rejection, or operator interruption. The planner must explicitly decide any recovery mutation; never replay automatically. Do not consume a recovery opportunity on a decision discarded due to pause/new guidance.
4. Rewrite the dual-system prompt/tool description to request a complete bounded interaction sequence with every known value and observable stopping condition. Jev handles menus, dates, filters, suggestions, and page transitions within that subgoal. Planner is for analysis, extraction, decisions requiring user input, and final reporting. Keep unsupported operations usable.
5. A confirmed already-correct text field should be logged as skipped and Jev should continue with the remaining subgoal, without counting the skip as an executed browser mutation. Maintain bounded no-progress behavior for repeated skips; never falsely claim all fields were finished. Native dropdown already-correct values may use the same safe skip handling. Never infer desired toggle state for an ambiguous click.
6. Preserve validation of Jev operation/target heads, existing approvals and visible failures, guidance/pause/stop handling. Test guidance arriving during the text helper as well as during Jev's decision before any mutation.

Tests first: demonstrate the normal planner currently receives direct UI tools and the skip currently stops a multi-field delegation. Then prove:
- configured/unconfigured tool availability and actual mutation gating;
- one normal delegation executes a multi-control sequence with only initial and final planner calls, including a page transition;
- a no-op field doesn't prevent subsequent fields from being filled;
- repeated no-op attempts terminate the fast subgoal visibly without pausing the run;
- direct password typing still waits for approval, regular typing cannot bypass delegation;
- errors/low confidence/stuck give a single explicit recovery opportunity, success/rejection/interruption do not;
- a failed browser mutation is not replayed automatically;
- pause/new guidance invalidate pending fast actions, including text-helper decisions;
- done remains a claim rather than silently marking the full goal verified.

Run focused tests and Ruff. Report changes and evidence to `/private/tmp/hyperagent-jev-delegation/task-1-report.md`.

## Task 2: Review and verify

Independent reviewer checks the task diff and concrete regression coverage. Controller runs the full offline suite and required frontend checks, verifies the committed UI remains unchanged, then restarts localhost:8780 with the existing config when safe to load the backend fix. No paid live success or token-savings claims without measured evidence; the user's next original Google Flights run is the live evaluation.

## Verification outcome

- Independent final review: passed with no actionable findings.
- `uv run ruff check .`: passed. `uv run pytest`: 118 passed.
- Frontend lint, typecheck and production build: passed. No frontend source changes since checkpoint 2fe7882.
- Local server restarted on port 8780 with the existing configuration.
- Backend fix remains uncommitted; no push or paid live run performed. Live routing and token savings remain to be measured with the original user task.
