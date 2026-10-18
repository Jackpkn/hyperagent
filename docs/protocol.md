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
| `attach` | `token: string` | Re-attach this socket to the run started under that `resume_token` (after a reload or dropped connection). Answered with `attached` and a replay, or `attach_failed`. |

## Server → client

### `hello`
`{ type, session_id, resume_token, model, models: string[], max_steps, configured: boolean, fast_model: string | null, has_saved_session?: boolean }`: sent on connect, on re-attach and when saved session state changes. `resume_token` is a secret for re-attaching to this session's run; the console keeps it in session storage (this tab only).

### `attached`
`{ type, goal, running: boolean, approval_mode }`: the socket took over a run whose page went away. It is followed by a replay of that run's messages so far (consecutive updates of one step collapsed to the latest, then the latest `frame`), then live messages. A run with no socket keeps going for `DETACH_GRACE_SECONDS` (default 300) and is stopped if nobody re-attaches; a pending approval or question waits for the operator.

### `attach_failed`
`{ type, message }`: the token names no detached run (it finished long ago, expired, or never existed). The console shows the message and keeps the saved turn as interrupted.

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
  url?: string,
  started_at: number, ended_at?: number,  /* epoch seconds */
  system?: "planner" | "fast",   /* System 2 LLM, or System 1 TypeSafe Jev */
  parent?: string,               /* fast steps: the planner step that delegated them */
  confidence?: number,           /* fast steps: Jev's calibrated confidence, 0-1 */
  alternatives?: { label: string, p: number }[],  /* fast steps: top choices with probabilities */
  latency_ms?: number            /* fast steps: Jev (+ text helper) latency */
}
```

### `plan`
`{ type, items: { text: string, status: "pending" | "active" | "done" | "skipped" }[] }`: the agent's own evolving plan.

### `findings`
`{ type, items: { source_url: string, data: object, unverified?: string[], step_id?: string, step_n?: number }[] }`: the full list of structured data recorded so far (replace, don't append). `unverified` lists any field keys whose extracted values could not be verified directly against the observed page text; `step_id` / `step_n` link each finding to the exact step snapshot where it was recorded.

### `approval`
`{ type, step_id, reason, action_label, target_label?, args }`: a risky step waits. Cleared by a later `step` update for that id.

### `question`
`{ type, step_id, question }`: the agent asked the operator. The operator answers with `guide`.

### `notice`
`{ type, level: "info" | "warn" | "error", message }`: recoveries, retries, loop detection, LLM errors, guidance acknowledged.

### `usage`
`{ type, llm_calls, input_tokens, cached_input_tokens, output_tokens, cost_usd, elapsed_s, fast_calls, fast_ms_total, text_calls, extract_calls }`
(`cost_usd` covers the planner and the extract model; TypeSafe responses carry token counts but no price.
`extract_calls` counts page-to-rows calls by the `extract` tool; `cached_input_tokens` is the part of
`input_tokens` read from the prompt cache, billed at a tenth of the input rate.)

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
