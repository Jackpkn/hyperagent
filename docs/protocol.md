# HyperAgent WebSocket protocol

One WebSocket (`/ws/agent`) per operator session. One browser context per socket.
All messages are JSON objects with a `type` field. The server never sends secrets.

## Client → server

| type | fields | meaning |
| --- | --- | --- |
| `start` | `goal: string`, `start_url?: string`, `approval_mode?: "risky" \| "always" \| "never"`, `model?: string`, `timezone?: string`, `continue_session?: boolean`, `persist_session?: boolean`, `operator_context?: string`, `conversation?: { goal, answer, columns?, rows? }[]` (≤12 earlier turns of this chat), `user_memory?: string[]` (≤20 remembered facts, ≤200 chars each) | Begin a run (or continue on the currently open browser page when `continue_session` is true). Default approval mode `risky`. `conversation` lets follow-ups refer to earlier turns; `user_memory` carries what the operator asked to be remembered. Both are summarised and stored by the console (in the browser), never on the server. |
| `pause` | – | Finish the in-flight action, then hold before the next decision. |
| `resume` | – | Continue a paused run. |
| `stop` | – | End the run; the agent produces a partial result from what it has. |
| `guide` | `text: string`, `pin_x?: number`, `pin_y?: number` | Operator guidance. Applied to the very next decision (resolving the pinned viewport coordinates if provided). Also answers an `ask_user` question. |
| `approve` | `step_id: string` | Execute the pending risky step once. |
| `reject` | `step_id: string`, `reason?: string` | Skip the pending step; the reason is given to the agent. |
| `set_mode` | `approval_mode: "risky" \| "always" \| "never"` | Change approval policy mid-run. |
| `takeover_click` | `x: number`, `y: number` | While paused, waiting for input, or after a run ends. Click at viewport coordinates (`frame.w × frame.h`). |
| `takeover_type` | `text: string`, `press_enter?: boolean` | While paused, waiting for input, or after a run ends. Type into the focused element. |
| `takeover_scroll` | `dy: number` | While paused, waiting for input, or after a run ends. Scroll the page. |
| `takeover_tab` | `tab_index: number` | Switch the active browser tab. |
| `save_session` | – | Save current browser cookies and localStorage to the server's persistent session profile. |
| `clear_session` | – | Clear the saved browser session profile on the server. |

## Server → client

### `hello`
`{ type, session_id, model, models: string[], max_steps, configured: boolean, fast_model: string | null, has_saved_session?: boolean }`: sent on connect and when saved session state changes.

### `status`
`{ type, state, step, detail? }`
`state` ∈ `idle | starting | running | thinking | acting | paused | awaiting_approval | awaiting_user | finishing | done | failed | stopped`.

### `frame`
`{ type, image: string /* base64 jpeg */, url, title, w, h, tabs: {index, title, url, active}[] }`
Sent continuously (~2–3 fps) while the browser exists, including while paused.

### `browser_session`
`{ type, active: boolean }`: `active: false` is sent after the browser closes, including idle expiry,
and when a takeover command reaches an already closed session. The UI retains the last image as a
read-only saved view, disables takeover and "Continue here", and explains that a new message opens a
fresh browser. Incoming live frames establish an active browser; disconnects clear that state.
Takeover still requires pause/user-input or a terminal run state, and an active browser. A terminal
run can accept takeover during final session cleanup; an expired session reports "closed", not "pause".

### `step`
A complete step record; sent when created and whenever it changes (same `id`, replace fields).
```
{
  type: "step",
  id: "s3", n: 3,
  status: "thinking" | "planned" | "awaiting_approval" | "running" | "ok" | "error" | "rejected" | "skipped",
  thought?: { evaluation: string, memory: string, next_goal: string,
              message?: string,   /* plain narration for the timeline */
              thinking?: string },
  action?: { name: string, args: object, label: string /* human sentence, e.g. 'Click "Search"' */ },
  target?: { label: string, rect: {x,y,w,h} } /* frame pixel space, if the action targets an element */,
  risk?: { risky: boolean, reason: string },
  result?: string,  /* short human-readable outcome */
  error?: string,
  url?: string,
  started_at: number, ended_at?: number,  /* epoch seconds */
  system?: "planner" | "fast",   /* System 2 LLM, or System 1 TypeSafe Jev */
  parent?: string,               /* fast steps: the planner step that delegated them */
  confidence?: number,           /* fast steps: Jev's calibrated confidence, 0-1 */
  alternatives?: { label: string, p: number }[],  /* fast steps: top choices with probabilities */
  latency_ms?: number            /* fast steps: Jev (+ text helper) latency */
}
```

With Jev configured, the planner prefers `delegate` for focused groups of related UI interactions with known
values and a visible stopping condition. All direct planner tools remain available for isolated actions and
recovery, including recovery requiring several decisions. Each action uses the latest observation and keeps
the existing approval policy; typing into an observed password field always requires approval.

Each delegated action uses the existing `system: "fast"` and `parent` fields. A field already holding the
requested text produces `status: "skipped"`, enters Jev's recent-action context, and does not count as a
browser mutation. Jev continues the remaining subgoal; repeated unchanged attempts return control visibly
without automatically pausing. Errors, stuck/unsure decisions, unchanged-state limits and subgoal budgets
return control to the planner. Recovery is explicitly chosen from fresh observations, never an automatic
replay of a browser mutation. Pausing or new guidance still discards pending decisions.
Jev's completion step remains a claim for the planner to check against the current page.

### `plan`
`{ type, items: { text: string, status: "pending" | "active" | "done" | "skipped" }[] }`: the agent's own evolving plan.

### `findings`
`{ type, items: { source_url: string, data: object, unverified?: string[], step_id?: string, step_n?: number }[] }`: the full list of structured data recorded so far (replace, don't append). `unverified` lists field keys whose values could not be matched against the observed page text; this check is not independent source verification. `step_id` / `step_n` identify the recording step. Its optional viewport capture may not show the field or the source page, especially for background extraction.

The console's per-value evidence disclosure uses these existing fields and the turn's steps/capture index;
there is no new server event or model request. Every nonempty result-row field must match a finding by
field name (trimmed, case-insensitive) and value (trimmed, otherwise exact). The `Source URL` / `source_url`
column matches the finding's top-level `source_url` metadata as a validated HTTP(S) URL. Reworded, derived or missing
values remain unlinked; multiple matching findings remain ambiguous. A unique match shows its source,
unverified-field warning, and the recording step's end time (start time if no end time exists), labelled
"Recorded at", not a source-observation timestamp. Capture inspection requires a successful step, a saved
capture entry, and matching step/source URLs (ignoring fragments only). These links survive normal chat
restoration and table sorting. Older reports without findings or recording metadata show unavailable
evidence rather than inferred provenance. Audit JSON already includes the findings and steps used here.

### `approval`
`{ type, step_id, reason, action_label, target_label?, args }`: a risky step waits. Cleared by a later `step` update for that id.

### `question`
`{ type, step_id, question }`: the agent asked the operator. The operator answers with `guide`.

### `notice`
`{ type, level: "info" | "warn" | "error", message }`: recoveries, retries, loop detection, LLM errors, guidance acknowledged.

### `usage`
`{ type, llm_calls, input_tokens, cached_input_tokens, output_tokens, cost_usd, elapsed_s, fast_calls, fast_ms_total, text_calls, extract_calls, accounting? }`
The legacy fields retain their meanings for old clients and budget checks.
(`cost_usd` covers the planner and the extract model; TypeSafe responses carry token counts but no price.
`extract_calls` counts page-to-rows calls by the `extract` tool; `cached_input_tokens` is the part of
`input_tokens` read from the prompt cache, billed at a tenth of the input rate.)

`accounting` is an optional, versioned measurement snapshot:

```ts
{
  schema_version: 1,
  run_id: string,                 // unique for each turn, not the whole chat
  summary: AccountingSummary,
  by_purpose: { planner: AccountingSummary, extract: AccountingSummary,
                jev: AccountingSummary, text: AccountingSummary },
  executed_fast_actions: number   // successful browser actions, excluding completion claims and skips
}
```

Each `AccountingSummary` contains `attempts`, `successful_responses`, `input_tokens`, `output_tokens`,
`cache_read_tokens`, `cache_write_tokens`, `duration_ms`, `known_cost_usd`, `total_cost_usd: number | null`,
`unknown_cost_count`, `unknown_usage_count`, and `cost_basis: "provider" | "estimate" | "unknown"`.
Tokens are available counts, not estimates for missing responses. Input totals already include cache tokens;
do not add the cache fields again. Duration is summed request time, not run wall time (calls may overlap).
Attempts include retries, errors, invalid replies, and cancellations. A successful response is not proof of a
successful browser action. Existing `fast_calls` counts usable Jev decisions; it is not an action count.

Unknown costs remain null per attempt. `known_cost_usd` sums available provider costs and configured-rate
estimates. `total_cost_usd` is null if any attempt lacks a cost. A complete configured-rate estimate is labeled
`estimate`, not a provider bill. TypeSafe cost remains unknown. Cancellation without a returned usage report
has unknown usage and cost, since cancellation does not prove the provider performed no work.

Usage events carry rollups only. The final `result.accounting` additionally contains `records` and
`delegations`, persisted with the chat and included in Audit JSON. Old chats without accounting continue to
show their legacy subtotal; they are not assigned fabricated historical usage.

Each call record contains `run_id`, `purpose`, nullable `step_id`/`parent_step_id`, `logical_call_id`,
`attempt_id`, one-based `attempt`, `provider`, `requested_model`, nullable `resolved_model`, `duration_ms`,
`outcome` (`success`, `invalid_response`, `provider_error`, `transport_error`, or `cancelled`), nullable
`input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `cost_usd`, and `cost_basis`.
Records contain no prompts, typed field values, API keys, or full provider responses.

A delegate parent step has optional `delegation` metadata, also present in final accounting's `delegations`:
`episode_id`, `run_id`, `parent_step_id`, `started_at`, `ended_at`, `reason`, `completion_claimed`,
`jev_attempts`, `text_attempts`, `executed_actions`, and `skipped_actions`. Reasons are `claimed_done`,
`stuck`, `low_confidence`, `no_change`, `attempt_budget`, `action_budget`, `observation_error`, `model_error`,
`action_error`, `rejected`, `paused`, `stopped`, or `guidance_changed`. Executed actions count successful
browser operations; skips exclude terminal/uncertainty decisions. Metadata does not enter model prompts or
change completion verification, approvals, interruption handling, limits, or planner fallback.

The existing cost limit still checks the legacy planner/extraction subtotal between planner steps. It is
not a hard limit on total provider spend. Accounting does not change that policy.

### `result`
```
{
  type: "result",
  success: boolean,          /* the agent's own claim; partial if stopped/failed */
  summary: string,           /* markdown */
  columns: string[],         /* table columns, may be empty */
  rows: object[],            /* each row keyed by column */
  sources: { title: string, url: string }[],
  issues: string[],          /* unresolved items, caveats */
  checklist: {               /* one item per requirement of the goal, as the agent judged it */
    requirement: string,
    met: boolean,
    evidence: string,
    step_id?: string,        /* the step where the evidence was seen; only steps that ran in this run */
    step_n?: number
  }[],
  assumptions: string[],     /* interpretations chosen where the goal was ambiguous */
  follow_ups: string[],      /* up to 3 suggested next goals; the UI only pre-fills them, never runs them */
  remember: string[],        /* ≤3 lasting facts/preferences, kept only if grounded in the operator's own words */
  accounting?: object       /* versioned snapshot above, including detailed records and delegations */
}
```
`success` is forced to `false` (with an issue) when any checklist item is unmet.
Followed by a `status` with `done`, `failed` or `stopped`.
