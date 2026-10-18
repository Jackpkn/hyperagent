# HyperAgent WebSocket protocol

One WebSocket (`/ws/agent`) per operator session. One browser context per socket.
All messages are JSON objects with a `type` field. The server never sends secrets.

## Client → server

| type | fields | meaning |
| --- | --- | --- |
| `start` | `goal: string`, `start_url?: string`, `approval_mode?: "risky" \| "always" \| "never"`, `model?: string`, `timezone?: string`, `continue_session?: boolean`, `persist_session?: boolean`, `operator_context?: string`, `conversation?: { goal, answer, columns?, rows? }[]` (≤12 earlier turns of this chat), `user_memory?: string[]` (≤20 remembered facts, ≤200 chars each) | Begin a run (or continue on the currently open browser page when `continue_session` is true). Default approval mode `risky`. `conversation` lets follow-ups refer to earlier turns; `user_memory` carries what the operator asked to be remembered. Both are summarised and stored by the console (in the browser), never on the server. |
| `pause` | – | Finish an action already executing, discard any decision not yet executed, then hold. Resuming does not revive a discarded decision. |
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
  verification?: { status: "verified" | "unverified" | "failed", detail: string },
  url?: string,
  started_at: number, ended_at?: number,  /* epoch seconds */
  system?: "planner" | "fast",   /* System 2 LLM, or System 1 TypeSafe Jev */
  parent?: string,               /* fast steps: the planner step that delegated them */
  confidence?: number,           /* fast steps: Jev's calibrated confidence, 0-1 */
  alternatives?: { label: string, p: number }[],  /* fast steps: top choices with probabilities */
  latency_ms?: number            /* fast steps: Jev (+ text helper) latency */
}
```

With Jev configured, routine planner `click`, `type_text` and `select_option` calls become
a parent `delegate` step with a fast child step. Explicit delegations may have multiple
children. Password entry stays with the planner and requires approval; one planner recovery
action is allowed after a failed/uncertain delegation, with a visible `notice`.
Jev `ACTIVATE`/`DEACTIVATE` decisions appear as `action.name: "click"` with boolean
`action.args.desired_state`; `TYPE_TEXT_ENTER` appears as `type_text` with `press_enter: true`.
Actions already satisfied by observed/fresh control state emit `status: "skipped"` with
the reason in `result`. Approval applies to the actual child action, retaining any risk
flag from the original planner call. No new event types are required.
Two failures of the same action on the same named control and page pause the run with
an error `notice`, even across observation ID changes, scrolls and delegation handoffs.
An explicit `resume` resets that failure budget. A successful action on the control also
clears its failures; a delegation handback alone does not count as recovery.

Targeted clicks, text entry and selections receive browser-side readiness checks after
approval. A changed/stale target or new operator guidance discards the action before
mutation. Post-action `verification` is optional for backward compatibility:
`verified` confirms a specific control value/state or link destination, not the whole task;
`failed` means the known expected state did not hold within the bounded check and emits
an error step; `unverified` means the outcome needs confirmation from a fresh page observation.
An unverified executed command retains `status: "ok"`, but the UI shows `?` rather than
a success checkmark. Verification only reads browser state; it makes no model calls.
Password values are compared in the browser and never included in verification details.

### `plan`
`{ type, items: { text: string, status: "pending" | "active" | "done" | "skipped" }[] }`: the agent's own evolving plan.

### `findings`
`{ type, items: { source_url: string, data: object, unverified?: string[], step_id?: string, step_n?: number }[] }`: the full list of structured data recorded so far (replace, don't append). `unverified` lists any field keys whose extracted values could not be verified directly against the observed page text; `step_id` / `step_n` link each finding to the exact step snapshot where it was recorded.

### `approval`
`{ type, step_id, reason, action_label, target_label?, args }`: a risky step waits. Cleared by a later `step` update for that id.

### `question`
`{ type, step_id, question }`: the agent asked the operator. The operator answers with `guide`.
The console keeps the question and answer together in the turn's saved feed, linked by `step_id`.
Answering does not start a new task or reset usage.

### `notice`
`{ type, level: "info" | "warn" | "error", message }`: recoveries, retries, loop detection, LLM errors, guidance acknowledged.

### `usage`
`{ type, llm_calls, input_tokens, cached_input_tokens, output_tokens, cost_usd, elapsed_s, fast_calls, fast_ms_total, text_calls, extract_calls }`
(`cost_usd` covers the planner and the extract model; TypeSafe responses carry token counts but no price.
`extract_calls` counts page-to-rows calls by the `extract` tool; `cached_input_tokens` is the part of
`input_tokens` read from the prompt cache, billed at a tenth of the input rate.)
These counters are cumulative snapshots for the current task, not deltas. Replace the task's
previous snapshot on each event. The console adds the latest snapshot of each distinct task
for chat totals, and each saved chat for the browser-local total. Cached input tokens are
already included in input tokens. `fast_calls` counts validated Jev decisions, including
failed/skipped actions and terminal decisions; it is not a count of successful browser actions.
The console does not infer token savings from this count.

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
  remember: string[]         /* ≤3 lasting facts/preferences, kept only if grounded in the operator's own words */
}
```
`success` is forced to `false` (with an issue) when any checklist item is unmet.
Followed by a `status` with `done`, `failed` or `stopped`.
