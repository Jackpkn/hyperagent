# HyperAgent

A browser agent that turns a plain-English goal into actions in a real Chromium browser. Watch the browser live, answer questions inline, and pause or take over when needed.

- **System 2 (Planner LLM — Claude Sonnet / Haiku / OpenRouter)** handles high-level strategy: planning, multi-step navigation, parallel multi-tab reading (`read_urls_parallel`), structured data extraction (`record_findings`), and final report synthesis (`done`).
- **System 1 ([TypeSafe Jev](https://docs.typesafe.ai/introduction) + a configurable text helper)** is the default executor for routine clicks, typing and selections when configured. It picks an operation and a typed target element `[id]` in one request **without sending screenshots**. The planner delegates related UI work as a subgoal; isolated planner UI calls are also routed through Jev. Actual latency and token savings depend on the task.

The console combines saved conversations, a live action timeline, a browser viewport, and structured reports with source links and open issues. The default approval mode pauses before detected risky actions such as submitting, buying, sending, or deleting.

[Run locally](#run-locally) · [Using the console](#using-the-console) · [Architecture](#architecture) · [Checks](#repository-layout--checks) · [WebSocket protocol](docs/protocol.md)

![Waiting for approval before submitting a form](docs/screenshots/approval.png)

---

## Core & Product Capabilities

| Capability | How HyperAgent Works |
| --- | --- |
| **Natural-language goal & follow-ups** | Enter any plain-English goal, optional start URL, model choice, and approval policy. When a run finishes, continue on the **same open browser page** (`Continue here`) or launch a fresh browser (`New browser`). |
| **Dual-System LLM + Jev orchestration** | The planner handles navigation, reading, extraction and final answers. Routine clicks, fills and selections go through Jev, including single actions. Related actions share a delegation, reducing planner round trips. Jev hands back a log when done, stuck, or below `45%` confidence. Passwords remain direct and approval-protected; after Jev fails or is unsure, the planner may make one fresh recovery action before returning to Jev. Without a Jev key, the planner acts directly. |
| **Token-saving Smart Vision & zero-screenshot System 1** | Live 2.5 fps JPEG frames stream directly to the operator UI over WebSocket (zero LLM tokens). Jev (`system1.py`) runs with `screenshot=False` over compact DOM element labels, and the Planner (`agent.py`) reads the same indexed element list with no screenshots by default (`AGENT_VISION=1` attaches one only after repeated errors or a click that changed nothing). `read_page`/`extract` use `reader.js`, which keeps the main content and drops nav, sidebars, cookie banners and tracking-link noise. Jev decision counts and latency appear in **Run details** (`⋯`); failed/skipped decisions are not presented as completed actions or measured token savings. |
| **Saved chats & live workspace** | A collapsible chat sidebar opens conversations at `/c/<chat-id>`. The workspace places the action timeline, findings and final report beside a live browser with target highlights and tab controls. The desktop header keeps task metrics and approval controls together; detailed usage lives in **Run details**. |
| **Inline questions & progress** | Agent questions and operator answers stay together in the timeline. The plan and action history start expanded. Action verification distinguishes a confirmed control state from an outcome that still needs inspection. |
| **Task & chat usage** | Track the current task, the sum of tasks in a conversation, and all saved chats in this browser. Jev decision counts include failed, skipped and terminal decisions; the UI does not turn them into estimated token savings. |
| **Visual Time-Travel Scrubber** | Every step captures its browser viewport snapshot. Click any step card (or its **Inspect** pill) in `Steps` to scrub back to the exact screenshot and target highlight from that moment, then click **Back to Live** to return. |
| **Visual "Point & Steer" Pin** | Click **Pin target** in the browser toolbar (or **Alt+Click** any element on the live viewport) to drop a coordinate pin `(x, y)`. The server resolves the exact underlying DOM element `[id]` via `elementFromPoint` and attaches it to your guidance message. |
| **Human-in-the-Loop control & Takeover** | **Pause / Resume (`Esc`) / Stop** at any time; pausing or sending guidance immediately invalidates any in-flight LLM decision so stale actions never execute. **Risky action gates**: `submit`, `buy`, `book`, `delete`, `send` (detected by keyword + model/Jev `irreversible` flag) and all `password` fields wait for operator approval. **Interactive Takeover**: click, type, scroll with your mouse wheel/trackpad, or switch tabs directly on the live browser when paused or waiting for input. |
| **Persistent Login Sessions & Autofill Profile** | Save authenticated cookies/`localStorage` across runs (`.hyperagent/storage_state.json`) via **Save login** / **Use saved login session**, and configure a local **Operator Profile** (`Profile` modal) for zero-typing form autofill. |
| **Parallel Multi-Tab Research & Self-Improving Domain Memory** | `read_urls_parallel` opens and extracts up to 4 `http(s)` URLs concurrently in background tabs without stealing focus. Successful runs automatically distill concise domain workflow hints into `.hyperagent/domain_memory.json`. |
| **Final report & table comparison** | Reports include a Markdown summary, structured data, source links, a requirements checklist and open issues. Compare tables with **Diff vs previous run**, or export Markdown, CSV and audit JSON. Incomplete tasks can return partial results with their gaps identified. |

---

## Architecture

```
 Operator Console (Next.js + Radix UI — apps/web)
 ┌───────────────────────────────────────────┐
 │ Top ControlBar: Status · Telemetry · Mode │
 ├────────────────────┬──────────────────────┤
 │ Left Sidebar Tabs  │ Right Live Browser   │
 │ • Steps (Timeline) │ • 2.5fps JPEG Stream │
 │ • Findings (Live)  │ • Target Box & Cursor│
 │ • Final Result     │ • Time-Travel View   │
 │                    │ • Point & Steer Pin  │
 │ Guidance Composer  │ • Direct Takeover    │
 └─────────┬──────────┴──────────▲───────────┘
           │ WebSocket /ws/agent │ JSON events + frames
           ▼                     │
 FastAPI Session & Orchestrator (hyperagent/)
 ┌──────────────────────────────────────────────────────────────┐
 │ Session (server.py): Slot Semaphore · Storage State · Memory │
 │   │                                                          │
 │   ▼                                                          │
 │ Agent Loop (agent.py): Observe → Decide → Approve → Execute  │
 │   ├─► System 2 Planner (llm.py): Strategy, Read, Extract     │
 │   └─► System 1 Fast Loop (system1.py + fast.py):             │
 │         ├─ TypeSafe Jev: 1 request → Op + Speculative Target │
 │         └─ Text helper: Value for text-entry operations     │
 │   │                                                          │
 │   ▼                                                          │
 │ BrowserSession (browser.py + dom.js):                        │
 │   Playwright Chromium · Reading-Order DOM Walker [id]        │
 │   Smart Inner-Container Scroll · Parallel Tab Reader · SSRF  │
 └──────────────────────────────────────────────────────────────┘
```

### Key Engineering Decisions

1. **Reading-Order DOM Indexing Instead of Raw HTML (`hyperagent/dom.js`, `hyperagent/browser.py`)**
   - Raw HTML wastes tens of thousands of tokens. Our DOM walker serializes visible text in reading order with interactive controls inline as `[12]<button>Find Flights</button>` and records each element's pixel bounding box (`rect`).
   - Models only emit integer `element_id`s from the latest observation—never brittle CSS/XPath selectors or arbitrary JS. Stale IDs fail loudly instead of clicking the wrong control.
   - Styled checkbox/radio inputs that are hidden, clipped or reduced to one pixel target their visible associated label. The observed state still comes from the native input; no forced click or mutation retry is used.

2. **Speculative Multi-Head System 1 (`hyperagent/fast.py`, `hyperagent/system1.py`)**
   - Each Jev call sends one multi-question request: an operation head (`CLICK`, `ACTIVATE`, `DEACTIVATE`, `TYPE_TEXT`, `TYPE_TEXT_ENTER`, `SELECT`, `SCROLL_*`, `SUBGOAL_DONE`, `STUCK`), speculative per-operation target heads (each offering only compatible elements), and an `irreversible` risk head.
   - Only the chosen operation's target head is consumed, and probability distributions are strictly validated before execution.
   - Checked, selected and pressed states determine which activation/deactivation targets are offered. Disabled controls and already-selected dropdown options are excluded. Grounded no-op checks skip satisfied controls and exact field values; fresh state is checked again after approval before execution. Controls without accessible state still require model judgment.
   - Pausing or new guidance invalidates an in-flight decision, including during text generation or approval. Failed browser mutations are reported without a fallback click, fill or selection attempt.
   - Targeted actions receive a read-only readiness check after approval, followed by a fresh identity/state check. Known field values, selected options and toggle states are checked after execution without model calls. Text is checked before sending Enter so rejected input is not submitted.
   - Each checked action reports `verified`, `failed` or `unverified`. Replaced controls and general clicks without a deterministic postcondition remain unverified (`?` in the timeline); navigation is not treated as proof of a completed transaction. Checks wait up to one second for known state updates, with a two-second verification timeout. Ambiguous outcomes require fresh observation, never an automatic mutation retry.

3. **Zero Silent Failures & Guaranteed Terminal Result (`hyperagent/agent.py`)**
   - Browser mutations (`click`, `type_text`, `select_option`) are **never** auto-retried; only transient LLM transport errors are retried with visible notices.
   - Two failures of the same action on the same named control/page pause for operator guidance, across changed observation IDs, scrolls, reloads and planner/Jev handoffs. Resume resets the failure budget. Verified control execution clears its failures; an unverified action or failed delegation handback does not.
   - Page-state hashing (`_mark_no_change`), action-signature warnings (`_loop_warnings`), and CAPTCHA/bot-wall detection (`_page_warnings`) provide additional recovery signals. Click timeouts report whether another element intercepted the pointer, the control was disabled, or it was not visible/stable.
   - Every run—even if stopped early or out of steps/budget—synthesizes an honest partial `result` from saved `findings`.

---

## Evaluation Evidence

**Historical stress test, October 17, 2026** ([details and raw logs](docs/runs/stress-test/README.md)): 18 goals covering research, tables, forms, logins, prices, flights and pagination. With Claude Sonnet as planner, 16 runs reported success in 13–60 seconds. The logs also record caveats such as inferred dates, secondary sources and an empty submitted date field; this is not a claim that all 16 satisfied every requirement. One task encountered a bot check and another found insufficient results. These runs predate the latest action-verification changes.

**Recorded dual-system runs** (Planner + TypeSafe Jev; historical results):

| Task | Planner calls | Jev calls | Time | Planner cost | Outcome |
| --- | --- | --- | --- | --- | --- |
| Fill and submit the httpbin pizza order form, report what the server received | 6 | 7 (avg 434 ms) | 32 s | $0.0019 | Planner delegated phone, email, size, toppings, and delivery time to Jev (6 actions at 96–100% confidence), then requested operator approval on `"Submit order"`. |
| Delegate only (no planner): choose Large and tick Bacon and Mushroom | 0 | 4 | 3.4 s | n/a | 3 clicks plus `SUBGOAL_DONE` at 95–100% confidence; page state verified afterwards. |

**Latest reliability validation, October 18, 2026:** 118 offline tests passed, followed by 9 console browser tests with model traffic mocked. Ruff, frontend lint, TypeScript checks and the production build passed. A browser-only check selected Notion's monthly billing control with one click and verified its checked state. The full planner → Jev → final-report flow has not been rerun since those changes. These checks made no paid model API calls.

---

## Run Locally

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node 22+.

```bash
uv sync
uv run playwright install chromium
cp .env.example .env          # set TYPESAFE_API_KEY (System 1) and ANTHROPIC_API_KEY / LLM_API_KEY
cd apps/web && npm ci && npm run build && cd ../..
uv run --env-file .env hyperagent-server
```

Open **http://localhost:8766**. Set `PORT` in `.env` to use a different port.

### Configuration

See [`.env.example`](.env.example) for the complete configuration. API keys stay on the server.

| Setting | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` or `LLM_API_KEY` | Planner credentials. The default provider uses Anthropic when its key is present; otherwise configure the OpenAI-compatible endpoint with `LLM_BASE_URL` and `LLM_MODELS`. |
| `TYPESAFE_API_KEY` | Enables Jev for routine UI execution. Leave empty to use the planner alone. |
| `TEXT_MODEL_*` | Configures the helper that supplies text-entry values. Defaults depend on the selected provider. |
| `AGENT_VISION=0` | Default: no screenshots sent to the planner. Set to `1` to allow screenshots for recovery after repeated errors or a click with no observed change. Jev stays text-only. |
| `MAX_STEPS`, `MAX_RUN_SECONDS`, `MAX_RUN_COST_USD` | Per-run limits. Defaults are 60 steps, 900 seconds and a $3 configured cost limit. |
| `BROWSER_WS_URL` | Optional remote CDP endpoint; otherwise launches local Chromium. |
| `PORT`, `WEB_DIST` | Server port and static frontend directory; defaults are `8766` and `apps/web/out`. |

### Development and live runs

For frontend hot reload, run `npm run dev` in `apps/web` alongside the backend. The frontend opens on port 3000 and connects to the backend on 8766 by default.

For the mock console, run `npm run mock` and `npm run dev:mock` in separate terminals inside `apps/web`. This does not require paid API calls.

The explicit live smoke runner uses the configured model APIs and can incur charges:

```bash
uv run --env-file .env python tools/run_task.py "<your goal>" --out run.json
```

## Using the Console

1. **Start from the launcher.** Enter a goal or choose a prompt card below the composer and edit it. Choose the planner model in the composer. **Browser settings** groups the optional start URL, saved logins and approval mode.
2. **Watch and guide.** The chat opens at `/c/<chat-id>`, with the timeline beside the live browser. Answer agent questions inline, send guidance, or pause to take over. Profile and memory controls remain available in the console.
3. **Inspect outcomes.** Read the action details and final report. A verified action confirms a specific value, state or link destination; it does not prove that the entire task succeeded. An unverified outcome needs further observation and is not automatically retried.
4. **Continue or return later.** Follow up in the same browser session while it remains available, or start a new browser. Open saved chats from the sidebar. Browser Back returns to the launcher when that was the previous page; Forward and direct-link refresh also work.

### Usage and storage

The header shows current-task metrics. **Run details** (`⋯`) separates task usage, the sum of distinct tasks in this chat, and all saved chats in this browser. Input and output counts are recorded snapshots; cached input is already included. Deleted chats and unrecorded historical usage are excluded. These totals are local records, not account-wide billing, and displayed costs do not include a Jev price when its API supplies none.

Live browser frames and stored inspection screenshots are for the console and do not themselves consume model tokens. Browser readiness checks, selected-state checks and post-action verification make no model calls. Fresh planner or Jev decisions still consume their normal API usage.

Chats and inspection screenshots are stored in this browser. A chat URL does not share the conversation across devices or restore an expired browser session. Leaving an active run stops it and saves its terminal result before switching conversations. Saved login state and domain memory live on the backend under `.hyperagent/`.

### Chat refresh troubleshooting

The Python server serves the application shell for `/c/<chat-id>`. If refreshing a chat returns 404 after an update, rebuild the frontend and restart the backend serving that port. A frontend rebuild alone does not reload Python routes. A chat missing from this browser's storage cannot be recovered from its URL alone.

---

## Deploy

The `Dockerfile` builds the Next.js static export and serves both the console and `/ws/agent` WebSocket from a single container with headless Chromium included:

```bash
docker build -t hyperagent .
docker run --rm --init --shm-size=1g -p 8766:8766 --env-file .env hyperagent
```

- **Railway** (`railway.json` included): `railway up`, set `TYPESAFE_API_KEY` and `ANTHROPIC_API_KEY` (or `LLM_API_KEY`), and generate a public domain.
- **Fly.io / Render**: deploy the `Dockerfile` with at least 1 GB RAM.
- **Hosted Browser (Browserbase / Steel / Browserless)**: set `BROWSER_WS_URL` to your remote CDP endpoint.

---

## Repository Layout & Checks

```
hyperagent/   agent.py (planner loop + controls + smart vision) · system1.py (Jev fast loop)
              fast.py (TypeSafe Jev + Haiku text helper) · browser.py (Playwright + parallel tabs + pin)
              dom.js (reading-order DOM walker) · control_state.py (satisfied-state checks)
              llm.py · tools.py · prompts.py · server.py
apps/web/     Next.js 15 console: Launcher, ChatSidebar, BrowserSettings, ControlBar,
              Timeline, InlineQuestion, StepCard, chat routing and usage aggregation,
              BrowserView, ApprovalCard, ResultsPanel, ResultReport, DataTable, OperatorModals
docs/         protocol.md (WebSocket contract) · runs/ (verified run logs & stress tests)
tests/        Offline unit, agent, System 1, route, and real-Chromium integration tests
tools/        run_task.py live CLI runner
```

Run the backend checks and frontend build (no paid API calls):

```bash
uv run ruff check . && uv run pytest
cd apps/web && npm run lint && npm run typecheck && npm run build
```

Console tests are skipped unless `CONSOLE_URL` is set. After building and starting the backend, run the UI checks with all agent WebSocket traffic intercepted:

```bash
CONSOLE_URL=http://localhost:8766 uv run pytest tests/test_console_ui.py -q
```
