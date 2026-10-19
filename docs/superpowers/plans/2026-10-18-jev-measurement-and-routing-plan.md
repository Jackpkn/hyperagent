# Jev Measurement Before Routing Changes — Implementation Plan

> **For agentic workers:** If implementation is subsequently authorized, use `superpowers:subagent-driven-development` or `superpowers:executing-plans` task by task. On 19 October the user authorized implementation of Tasks 1–3 and explicitly excluded eval work. No commits, pushes, deployment, or paid trials are authorized.

**Goal:** Establish reliable evidence about where HyperAgent spends model calls, tokens, and time before changing its planner/Jev routing.

**Architecture:** Add run-scoped measurement around existing provider requests and delegation episodes. Preserve the current decision and execution paths. Use independently graded evaluations to decide whether a separate routing experiment is warranted.

**Tech Stack:** Python, FastAPI, Playwright, Anthropic/OpenRouter/TypeSafe clients, pytest; Next.js/TypeScript for existing telemetry displays.

**Spec:** The approved discussion and latest planning-only request, captured in “Scope and decision” below. Repository contract: `AGENTS.md`, `README.md`, and `docs/protocol.md`.

**Inspected baseline:** `89ba052` on `main`, 18 October 2026. Recheck the implementation against this plan if the code changes. The untracked `apps/web/src/app/.globals.css.swp` belongs to the existing workspace and must be left alone.

## Scope and decision

The question is whether Jev can reduce unnecessary planner work while preserving reliability. Existing evidence does not establish that more delegation would improve every task. Implement measurement first, then compare configurations. Do not implement a new router, memory retrieval, or an Obsidian integration in this increment.

The historical `2026-10-18-jev-delegation.md` describes forced delegation and restricted planner recovery. **Do not implement that routing policy.** This plan preserves direct planner tools and unrestricted recovery within the existing run budgets.

## Global constraints

- Preserve observe → decide → approval → execute → stream. No hardcoded website workflows in production.
- Keep latest-observation element IDs and selected-target-head validation. Models must not emit selectors or code.
- Never automatically retry browser mutations. Existing model retries remain separate from action execution.
- Pause, stop, and new guidance must still invalidate pending decisions before execution.
- Preserve approval rules, including password fields. A Jev completion claim is not independently verified task completion.
- Keep current confidence thresholds, delegation limits, no-change handling, and planner fallback unchanged during measurement.
- Keep measurement metadata out of model prompts, observations, and existing human-readable handback strings.
- Preserve frontend layout, colors, one-row toolbar, chat routes, and restored reports. Only telemetry semantics/copy are in scope.
- Keep protocol documentation, server events, and frontend types synchronized; old saved chats must remain readable.
- Tests use scripted providers and isolated browser fixtures, never paid APIs. Live comparisons require a separate explicit decision to spend.
- No commit or push steps are part of this handoff.

## Verified findings and limits

| Finding | Evidence | Implication |
| --- | --- | --- |
| Jev already supports multi-action delegated work. | `hyperagent/system1.py::_delegate`, maximum 15 attempts with fresh observations. | Do not rebuild an execution loop that already exists. |
| Direct planner recovery is deliberately available. | `README.md`, planner tools, `tests/test_system1.py`. | Routing experiments must preserve this escape path. |
| Jev usage is returned but not accumulated. | `FastDecision.usage` in `fast.py`; `_delegate` counts calls/latency only. | Current totals cannot prove complete cost savings. |
| Text-helper usage is discarded. | `fast.py::write_text`; `system1.py::_fast_act` increments only `text_calls`. | Include helper requests when comparing delegation costs. |
| Some failed/invalid attempts are absent from totals. | Provider retry/validation paths in `llm.py`, `anthropic_backend.py`, `fast.py`. | Instrument responses before parsing and validating decisions. |
| Handoff reasons are free-form text. | `system1.py::_handback`. | Structured reasons would make comparisons reliable without changing behavior. |
| UI savings are a heuristic. | `ControlBar.tsx`, `ResultReport.tsx`: calls × 4,000. | Remove this as evidence of measured savings; calls also differ from actions. |
| Model clients are shared by server sessions. | `hyperagent/server.py` creates module-level `LLM` and `FAST`. | Never store the current run's collector on a shared client. |

Existing local artifacts inspected during planning:

| Artifact | Planner / Jev / helper calls | Recorded cost subtotal | What it establishes |
| --- | --- | --- | --- |
| `artifacts/evals/submission-prefilled-01.json` | 4 / 0 / 0 | $0.0508385 | One independently graded pass; no Jev use. |
| `artifacts/evals/submission-autocomplete-01.json` | 4 / 0 / 0 | $0.027106 | One independently graded pass; no Jev use. |
| `artifacts/submission/live-form.json` | 2 / 9 / 5 | $0.021376 | Eight Jev actions, then a completion claim. Action trace/smoke evidence, not an independent grader. |
| `artifacts/submission/live-ui.json` | 5 / 0 / 0 | $0.08689 | Catalogue result independently checked against sources; four extraction calls. |
| `artifacts/submission-public/live-ui.json` | 7 / 0 / 0 | $0.10855 | Deployed catalogue result checked; two extraction calls. |

These are individual runs, not a controlled comparison or a success-rate estimate. Artifact files are ignored by Git; committed summaries are in `docs/runs/submission-2026-10-18/`. All listed costs omit Jev and helper costs. The form's two planner calls do not establish waste: planning and final verification/reporting are legitimate work.

TypeSafe documents input/output token usage and the resolved model in its [API response](https://docs.typesafe.ai/api). That does not provide a documented billed-dollar field. Preserve unknown cost rather than inventing a rate.

## Review focus

1. **Concurrent users and parallel extraction:** no cross-run attribution or double counting. Covered in Task 1.
2. **Retries, malformed responses, cancellation:** an unusable decision may still incur usage; missing response data remains unknown. Covered in Task 1.
3. **Interruption, rejection, and ambiguous completion:** instrumentation must not cause an action, replay, or premature success. Covered in Task 2.
4. **Old saved chats and partial accounting:** missing telemetry must not become zero cost, broken rendering, or lost reports. Covered in Task 3.
5. **Misleading comparisons:** retain failed trials and distinguish configured Jev from actual Jev use. Covered in Task 4.

## Task 1 — Account for model attempts without changing decisions

**Files:** Create `hyperagent/telemetry.py`, `tests/test_telemetry.py`. Modify `hyperagent/agent.py`, `hyperagent/llm.py`, `hyperagent/anthropic_backend.py`, `hyperagent/fast.py`, `hyperagent/extract.py`, `hyperagent/system1.py`. Extend `tests/test_anthropic_backend.py`, `tests/test_units.py`, and test fakes where necessary.

**Interface decisions:**

- `CallContext` is an immutable dataclass containing `run_id`, `step_id: str | None`, `parent_step_id: str | None`, and `purpose: Literal["planner", "extract", "jev", "text"]`.
- `CallRecord` describes one physical provider attempt: context, unique `logical_call_id` and `attempt_id`, attempt number, provider, requested/resolved model, monotonic duration, outcome, nullable input/output/cache token counts, nullable USD cost, and `cost_basis: Literal["provider", "estimate", "unknown"]`.
- Outcomes are `success`, `invalid_response`, `provider_error`, `transport_error`, or `cancelled`. Record returned usage even when outcome is not success. Missing usage is `None`, not zero. Known-zero usage is allowed only when actually reported.
- `RunLedger.record(record: CallRecord) -> None` is idempotent by attempt ID. `RunLedger.snapshot() -> dict[str, Any]` returns `schema_version: 1`, records, and summaries by purpose: attempts, successful responses, known tokens/cost, unknown-usage count, unknown-cost count, and duration.
- Implementation adjustment: `RunLedger.scope(purpose, step_id, parent_step_id)` establishes a task-local `CallContext`; a `model_call` wrapper groups physical attempts, including nested native client calls. ContextVars reset in `finally` and child tasks inherit the active scope. This preserves existing provider interfaces and test doubles without shared-client mutable run state. A new ledger belongs to each Agent run, not the shared client or the whole chat. Concurrency tests cover isolation.
- Keep existing return values, `Decision`, and existing budget counters compatible. The ledger is the new measurement source, not an extra contribution to legacy totals. Do not sum both representations.

- [ ] Write failing ledger tests: duplicate attempt ID counts once; two interleaved runs stay separate; concurrent extraction records all distinct calls; unknown cost never produces a complete total.
- [ ] Write provider tests with scripted responses: retry followed by success records both attempts; a response with usage but invalid action/JSON retains usage; cancelled request without a response records unknown usage; valid response discarded after guidance still counts its usage.
- [ ] Run `uv run pytest tests/test_telemetry.py tests/test_anthropic_backend.py tests/test_units.py -q`; confirm failures concern missing measurement behavior.
- [ ] Implement the run-local ledger and explicit propagation. Instrument each transport attempt once; capture usage before content/tool parsing. Finish the attempt after validation determines its outcome, including failure/cancellation paths. For a cancelled request that never returns usage, do not assume the provider did no work.
- [ ] Normalize provider usage without double-counting cached tokens. Preserve cache read/write breakdown. Distinguish provider-reported costs from configured-rate estimates; an unknown Anthropic model rate must yield unknown cost in this ledger, not the legacy zero estimate. Do not guess Jev pricing.
- [ ] Include text-helper attempts for both native Anthropic and OpenRouter paths. Store only allowlisted numeric usage/status/model metadata, not prompts, typed values, credentials, or full provider responses.
- [ ] Run the focused tests above plus `uv run pytest tests/test_agent.py tests/test_system1.py -q`. Confirm scripted action order and existing budget behavior remain unchanged.

**Acceptance:** Every attempted request in a scripted run has exactly one record, attributed correctly, including failures. No extra model requests occur. Existing budgets still apply to their documented legacy subtotal; this work must not silently change when a run stops. Unknown costs mean the current budget is still not a hard full-spend cap.

## Task 2 — Record why delegation ends

**Files:** Modify `hyperagent/system1.py`, `hyperagent/telemetry.py`, `hyperagent/agent.py`; extend `tests/test_system1.py`, `tests/test_telemetry.py`, `tests/test_units.py`.

**Interface decisions:**

- `DelegationRecord` contains a run-scoped episode ID, parent step ID, start/end time, Jev/helper attempt counts, executed-action count, skipped-action count, reason code, and `completion_claimed: bool`.
- Reason codes: `claimed_done`, `stuck`, `low_confidence`, `no_change`, `attempt_budget`, `action_budget`, `observation_error`, `model_error`, `action_error`, `rejected`, `paused`, `stopped`, `guidance_changed`.
- Add `RunLedger.record_delegation(record: DelegationRecord) -> None` and a `delegations` collection to its snapshot. Finalize one episode on every exit from `_delegate`, including exceptional cancellation; cancellation during stop maps to `stopped`, otherwise expose it as a model error rather than claiming completion.
- Preserve `_handback`'s returned text and existing callers' behavior. Capture a local reason alongside each existing return path. Terminal handling can return reason metadata internally, but must not alter the existing terminal precedence or confidence policy.

- [ ] Write failing parametrized tests for every reason, including stop and guidance while a decision/helper request is in flight. Assert exactly one finalized episode and zero extra browser actions.
- [ ] Add count tests: eight executed actions plus `SUBGOAL_DONE` means nine Jev decisions, eight actions, one claimed-completion handoff. A skipped already-correct field counts as a skip, not an action, and delegation continues.
- [ ] Retain and exercise `test_jev_done_is_a_claim_until_planner_inspects_current_page`; assert a claim creates neither an agent result nor a terminal success event.
- [ ] Implement episode recording without changing the loop, approvals, errors, or fallback. Attach optional telemetry to the parent step for export, but preserve label/result text. Assert `prompts.step_context(...)` output is identical with and without the metadata.
- [ ] Run `uv run pytest tests/test_system1.py tests/test_telemetry.py tests/test_units.py -q`. Specifically retain no automatic mutation retry, rejected-action handling, and multi-action planner recovery tests.

**Acceptance:** A trace can distinguish a successful delegated subgoal, unsupported work, uncertainty, interruption, and actual failure. It does not automatically label a planner call “unnecessary”; that requires task-level evidence.

## Task 3 — Export honest measurement and retain UI compatibility

**Files:** Modify `docs/protocol.md`, `hyperagent/agent.py`, `apps/web/src/lib/protocol.ts`, `apps/web/src/lib/agent-state.ts`, `apps/web/src/lib/chat-model.ts` if needed, `apps/web/src/components/ControlBar.tsx`, `apps/web/src/components/ResultReport.tsx`, `README.md`. Extend `tests/test_chat_refresh.py` and `tests/test_console_design.py` using their existing conventions; place pure aggregation tests in `tests/test_telemetry.py`.

**Interface decisions:**

- Add optional `usage.accounting` with schema version, per-purpose rollups, cost coverage, and executed fast-action count. Send rollups in normal usage events; do not retransmit the entire growing call ledger after every action.
- Add optional `step.delegation` with the finalized episode record. Export the detailed ledger once with the final result's optional `accounting` field and in eval artifacts; preserve existing result fields.
- `known_cost_usd` is only the sum of available costs. `total_cost_usd` is nullable and present only when every attempt has a cost value; include `cost_basis` so a complete estimate is not represented as an actual bill. Usage completeness is separate from cost completeness.
- Old records without accounting retain their original numbers with an explicit legacy-subtotal description. Do not manufacture historical Jev usage.

- [ ] Write compatibility tests for both legacy and new events/results: reducer preserves accounting, chat save/restore preserves report/findings/accounting, absent fields do not crash or become zero-complete totals.
- [ ] Add assertions that fast calls are labeled as calls and browser actions as actions. Remove `fast_calls * 4000` savings claims from both displays and related README claims; measured comparisons belong in eval reports.
- [ ] Implement the additive protocol fields and reducers. Use existing tooltip/report telemetry space for “Known cost” or “Estimated total” as appropriate; retain the compact toolbar and current styling. Keep detailed records in Audit JSON rather than a new UI panel.
- [ ] Update `docs/protocol.md` and README to explain incomplete provider accounting and unchanged budget semantics.
- [ ] Run `uv run pytest tests/test_chat_refresh.py tests/test_console_design.py tests/test_telemetry.py -q`. In `apps/web`, run `npm run lint`, `npm run typecheck`, and `npm run build`.
- [ ] Exercise the UI locally using replayed/scripted events: legacy chat refresh, new chat refresh, long report, narrow viewport, completed and stopped runs. Check browser console errors and ensure no extra toolbar row or report clipping. No live paid agent task is needed for this check.

**Acceptance:** Audit data is inspectable and retained on refresh; the UI no longer presents a heuristic as measured savings. Token and dollar counts remain separate concepts.

## Task 4 — Establish a controlled comparison, one case at a time

**Files:** Modify `tools/evals/runner.py`, `tests/test_eval_runner.py`, `docs/evals/README.md`. Add `tools/evals/multifield_form.html`, `tools/evals/multifield_form.py`, `tests/test_eval_multifield_form.py`. Reuse the existing fixture isolation in `tools/evals/fixture.py`.

**Interface decisions:**

- Register `multifield-form` through the same case interface as `prefilled-form` and `autocomplete`. Keep fixture-specific goals and grading logic entirely under eval tooling/tests.
- Report the ledger snapshot, independently computed executed-action counts, setup/run/cleanup durations, requested and returned model IDs, exact budgets, all routing settings, fixture/goal versions, and hashes covering planner prompts/tools plus Jev rules, target rules, and question criteria.
- Record cache usage and unavailable cache metadata explicitly. Configuration says `planner-only` or `optional-jev`; also record whether Jev was actually invoked. Optional Jev with zero calls must not be reported as a Jev execution benchmark.

- [ ] Write runner tests for complete/incomplete cost coverage, failed trials, cancellation, resolved-model reporting, and separate elapsed-time fields. Ensure per-call plus legacy usage is never added twice.
- [ ] Implement report metadata while preserving independent pass/fail grading, output overwrite protection, and safe unattended approval behavior.
- [ ] Implement one isolated multi-field, two-page form fixture: requested values for six editable fields, two already-correct controls, and a review page. Log browser events outside page state. Passing requires every requested value, no events on correct controls, one review transition, agreement with visible review data, and no outside requests/tabs. The fixture must support either planner-only or delegated execution.
- [ ] Write grader tests that reject false completion, missing fields, redundant correct-field edits, stale/reloaded review data, and double review transitions. Include a correct scripted execution for each supported routing configuration. These prove the grader, not model competence.
- [ ] Run `uv run pytest tests/test_eval_runner.py tests/test_eval_prefilled_form.py tests/test_eval_autocomplete.py tests/test_eval_multifield_form.py -q` before considering any live trial.
- [ ] Document a future matched comparison: same clean revision, same goal/fixture/start state, pinned planner/helper/Jev model versions where available, same budgets, fresh browser contexts, alternating arm order. If a model is an unpinned alias, disclose that limitation. Keep cache conditions visible instead of assuming they match.

**Future paid-trial gate:** Start with one trial per arm per case only after the user chooses to run them. Inspect the harness and ledger before repeating. Preserve all failures, timeouts, interruptions, and costs. Five trials per arm can expose problems but are exploratory, not evidence of a stable success rate. Report individual observations, pass counts, and median/range latency; do not advertise reliable tail latency from a tiny sample. Unknown provider cost prevents a claim of full dollar savings.

## Routing decision after these tasks

Use the results to choose the next action; do not preselect the answer:

| Observed evidence | Next action |
| --- | --- |
| Planner uses fewer calls on short tasks and completes them reliably. | Keep direct planner execution for those tasks. |
| Jev handles long, well-specified subgoals with lower measured cost/time and comparable correctness. | Propose one focused delegation-prompt experiment for that workload. |
| Repeated handbacks come from unsupported operations or ambiguity. | Preserve planner recovery; investigate the specific unsupported capability separately. |
| Text helper or repeated no-op decisions dominate. | Design a focused value/context optimization, with state-verification tests; do not remove validation to save calls. |
| Costs are incomplete or results vary widely. | Improve evidence; do not claim savings or promote a routing change. |

Any routing candidate gets a separate design, isolated implementation, and explicit promotion criteria fixed before its trial. Change one behavior at a time. Include approval, interruption, API-failure, repeated-label, and completion-verification regressions before promotion. Keep the existing planner fallback and a switch back to the baseline. There is no evidence here to justify mandatory delegation, an extra Jev call after every click, or automatic final success based on Jev confidence.

Memory is a later independent project. First identify repeated knowledge work that would benefit, then evaluate scoped retrieval with source/time metadata. Prices, availability, selected controls, and other changing facts still require fresh observation. Do not add a memory model call to every action by default.

## Final implementation verification and stopping point

- [ ] From repository root: `uv run ruff check .` and `uv run pytest`.
- [ ] In `apps/web`: `npm run lint`, `npm run typecheck`, `npm run build`.
- [ ] Review the diff against the inspected baseline: no routing/tool-policy changes, no site-specific production behavior, no altered approval/interruption semantics, no added live API calls in tests.
- [ ] Confirm old and new reports survive refresh and accounting metadata does not enter model context.
- [ ] Deliver measurements and known limitations. Stop before routing/memory implementation or deployment. Do not commit or push without a later user request.

## Planning self-review

The plan separates observed facts from hypotheses, preserves current recovery, covers all four request purposes, includes concurrency/retry/cancellation accounting, retains legacy chats, and requires independent browser-state grading. All five review risks have named tests/tasks. Tasks 1–3 establish measurement; Task 4 establishes a comparison harness. No performance gain is assumed and no broader orchestration rewrite is authorized.


## Implementation status — 19 October 2026

- Tasks 1–3 implemented in the existing authorized checkout, without Git operations. Provider accounting,
  delegation records, additive protocol/UI support, chat persistence, and honest cost labels are present.
- Task 4 is excluded by the user's latest instruction. No eval cases were added or run, and no live model
  requests were made. Offline regression tests use fake providers or local WebSocket/browser fixtures.
- Review fixes: retain input/cache metadata on cancelled native streams while leaving final output/cost
  unknown; classify invalid extraction row schemas as invalid responses; publish usage after discarded or
  failed planner decisions. These do not change action execution or planner recovery.
- Known minor limitation: a text-helper failure remains grouped as `action_error` in delegation metadata,
  matching the existing handback path. Its individual call record still identifies purpose `text` and the
  model failure. A more specific delegation classification is deferred.
- Existing budget semantics are unchanged: the limit uses the legacy planner/extraction subtotal. Jev dollar
  costs remain unavailable; complete total-cost claims are suppressed when any attempt's cost is unknown.
- Final verification: **146 non-eval regression tests passed**; Ruff, frontend lint, typecheck, and production
  build passed. `git diff --check` passed. HEAD remains `89ba052`; prompts, tool policy, browser execution,
  and eval files are unchanged. Changes remain uncommitted and undeployed.
