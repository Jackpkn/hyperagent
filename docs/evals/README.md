# HyperAgent evaluations

These cases evaluate actual browser outcomes independently of the agent's success claim. They are test
fixtures supplied as goals, never runtime plans or site-specific rules in the agent. Add cases individually
after validating their graders. Two cases are implemented. Each passed one live trial on 18 October 2026;
see [the evidence and limitations](../runs/submission-2026-10-18/README.md). This is not a success-rate estimate.

## 001 — Preserve a prefilled form

The isolated contact-preferences page starts with Name **Alex Tester**, Country **India**, **Monthly** billing,
and Newsletter **off**. Email and Company are empty. The goal asks for **alex@example.test** and
**Example Labs**, leaves the correct controls untouched, and requests **Review details** once.

Passing requires all of these independent checks:

- Final form values match the requested values.
- The visible review contains the complete requested values, captured when Review was clicked.
- Review was opened exactly once.
- The four correct controls received no click, input or change events, including before a reload.
- The browser stayed on the fixture page without additional tabs or external requests.

The fixture records events outside the page in the eval harness. A model's `success=true` cannot override
failed checks. A stopped, timed-out or failed run does not pass. This first case does not judge prose quality,
autocomplete, calendars, approval recovery, or external website reliability; those require separate cases.

The fixture is served by a Playwright route inside a fresh browser context. Its `.test` URL makes no real
website request. Other requests in that context are blocked and recorded. Production network rules and
agent behavior are unchanged. The default eval approval mode is `risky`; a question, approval request or
pause stops this unattended trial. The harness never supplies an answer or automatically approves it.

## 002 — Commit an autocomplete selection

The isolated route explorer asks for **London, United Kingdom (LON)**. Its suggestions also include
**London, Ontario, Canada (YXU)** and **Londonderry, United Kingdom (LDY)**. Typing even the exact destination
label does not commit a selection. The agent must choose a suggestion, click **Show routes**, and verify
the displayed destination. Mouse and keyboard selection are both supported.

Passing requires the committed destination ID, input label, and visible result ID/label to agree with the
requested destination. The grader checks browser state and recorded selection/search events independently
of the agent's completion claim. Editing the input invalidates the selection and hides old results;
reloading cannot reuse historical success. Choosing a wrong suggestion and correcting it is allowed.
Additional tabs and external requests fail the case, even if the tab was later closed.

This case checks autocomplete selection and result verification. It does not simulate a real flight search,
network latency, delayed suggestions, calendar selection, or booking. Those need separate cases.

## Offline verification — no paid calls

```bash
uv run pytest tests/test_eval_prefilled_form.py tests/test_eval_autocomplete.py tests/test_eval_runner.py -q
```

These tests validate the grader and runner using real Chromium and scripted model decisions. They deliberately
test false completion claims, redundant actions, incomplete review, reloads, temporary tabs, blocked navigation, timeout,
interruption, and report overwrite protection. They are **not** a measurement of real model competence.

## Explicit live trials — paid model calls

Run from the repository root with the configured model credentials. Use the same explicit `--model` value
for both arms of a comparison. Keep the commit, fixture version, budgets and starting state the same.

```bash
uv run --env-file .env python tools/run_task.py \
  --eval-case prefilled-form --no-fast --max-steps 12 --timeout 120 --max-cost 0.25 \
  --out artifacts/evals/prefilled-form/planner-01.json

uv run --env-file .env python tools/run_task.py \
  --eval-case prefilled-form --max-steps 12 --timeout 120 --max-cost 0.25 \
  --out artifacts/evals/prefilled-form/jev-01.json
```

Without `--no-fast`, Jev must be configured; the runner does not silently relabel a planner-only run.
For case 002, use `--eval-case autocomplete` and new output paths, for example:

```bash
uv run --env-file .env python tools/run_task.py \
  --eval-case autocomplete --no-fast --max-steps 12 --timeout 120 --max-cost 0.25 \
  --out artifacts/evals/autocomplete/planner-01.json

uv run --env-file .env python tools/run_task.py \
  --eval-case autocomplete --max-steps 12 --timeout 120 --max-cost 0.25 \
  --out artifacts/evals/autocomplete/jev-01.json
```

Every command runs one fresh trial. Existing output files are refused. Exit code **0** means all checks
passed and the agent completed; **1** means the trial failed; invalid CLI arguments return **2**.
The timeout covers the agent run, not browser setup. No eval is launched by the app or by ordinary pytest.

The JSON report includes the independent verdict and evidence, agent result and success claim separately,
terminal state, events, elapsed time, executed actions, step errors, configuration, Git revision/dirty state,
prompt/tool-schema hash, fixture hash, and recorded usage. Dirty runs are exploratory; use clean, pinned
revisions for repeatable comparisons. `artifacts/` is ignored by Git.

**Usage limitation:** existing engine token/cost totals cover planner and extraction calls only. Jev and
text-helper costs are missing. The report therefore sets `total_cost_usd` to `null` and does not invent
token savings. `--max-cost` limits only that tracked subtotal, is checked between planner steps, and can
be exceeded by an in-flight call. It is not a hard total-spend cap.

Start with one trial per configuration to check the harness. Then repeat each configuration at least three
times using new output names, preserving failures and timeouts. Compare independently verified pass counts
and latency/call counts; defer full cost comparisons until complete provider accounting is implemented.

## Next cases, one at a time

1. Calendar: the selected date and returned results must agree.
2. Failure recovery: injected API errors must not strand the planner or replay mutations automatically.
3. Repeated labels: the chosen control must belong to the intended row.
4. Approval: rejection prevents a mutation; approval permits one fresh action.

Broader benchmark integration can follow these local regressions. Reference approaches:
[BrowserGym](https://github.com/ServiceNow/BrowserGym),
[AgentLab](https://github.com/ServiceNow/AgentLab), and
[independent outcome grading](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).
