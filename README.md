# HyperAgent

A dual-system autonomous browser agent with a transparent, steerable 2-pane operator console.

- **System 2 (Planner LLM — Claude Sonnet / Haiku / OpenRouter)** handles high-level strategy: planning, multi-step navigation, parallel multi-tab reading (`read_urls_parallel`), structured data extraction (`record_findings`), and final report synthesis (`done`).
- **System 1 ([TypeSafe Jev](https://docs.typesafe.ai/introduction) + Haiku text micro-helper)** is the default executor for routine clicks, typing and selections when configured. It picks an operation and a typed target element `[id]` in one request **without sending screenshots**. The planner delegates related UI work as a subgoal; isolated planner UI calls are also routed through Jev. Actual latency and token savings depend on the task.

Give it any natural-language goal. It drives a real Chromium browser, streams every thought and target bounding box live, pauses before irreversible actions, lets you take over or drop a visual pin on the page to steer it mid-run, and finishes with a verified summary, sortable/diffable table, and CSV/JSON/Markdown exports.

![Waiting for approval before submitting a form](docs/screenshots/approval.png)

---

## Core & Product Capabilities

| Capability | How HyperAgent Works |
| --- | --- |
| **Natural-language goal & follow-ups** | Enter any plain-English goal, optional start URL, model choice, and approval policy. When a run finishes, continue on the **same open browser page** (`Continue here`) or launch a fresh browser (`New browser`). |
| **Dual-System LLM + Jev orchestration** | The planner handles navigation, reading, extraction and final answers. Routine clicks, fills and selections go through Jev, including single actions. Related actions share a delegation, reducing planner round trips. Jev hands back a log when done, stuck, or below `45%` confidence. Passwords remain direct and approval-protected; after Jev fails or is unsure, the planner may make one fresh recovery action before returning to Jev. Without a Jev key, the planner acts directly. |
| **Token-saving Smart Vision & zero-screenshot System 1** | Live 2.5 fps JPEG frames stream directly to the operator UI over WebSocket (zero LLM tokens). Jev (`system1.py`) runs with `screenshot=False` over compact DOM element labels, and the Planner (`agent.py`) reads the same indexed element list with no screenshots by default (`AGENT_VISION=1` attaches one only after repeated errors or a click that changed nothing). `read_page`/`extract` use `reader.js`, which keeps the main content and drops nav, sidebars, cookie banners and tracking-link noise. Jev decision counts and latency appear in **Run details** (`⋯`); failed/skipped decisions are not presented as completed actions or measured token savings. |
| **Transparent 2-pane workspace** | **Right pane**: Full-height live browser viewport with animated cursor/bounding-box target highlights (`target-box`) and clickable multi-tab bar. **Left sidebar**: Clean 3-tab layout (`Steps`, `Findings`, `Final Result`) with collapsible thinking/memory drawers, collapsible plan progress, and expandable report view. |
| **Visual Time-Travel Scrubber** | Every step captures its browser viewport snapshot. Click any step card (or its **Inspect** pill) in `Steps` to scrub back to the exact screenshot and target highlight from that moment, then click **Back to Live** to return. |
| **Visual "Point & Steer" Pin** | Click **Pin target** in the browser toolbar (or **Alt+Click** any element on the live viewport) to drop a coordinate pin `(x, y)`. The server resolves the exact underlying DOM element `[id]` via `elementFromPoint` and attaches it to your guidance message. |
| **Human-in-the-Loop control & Takeover** | **Pause / Resume (`Esc`) / Stop** at any time; pausing or sending guidance immediately invalidates any in-flight LLM decision so stale actions never execute. **Risky action gates**: `submit`, `buy`, `book`, `delete`, `send` (detected by keyword + model/Jev `irreversible` flag) and all `password` fields wait for operator approval. **Interactive Takeover**: click, type, scroll with your mouse wheel/trackpad, or switch tabs directly on the live browser when paused or waiting for input. |
| **Persistent Login Sessions & Autofill Profile** | Save authenticated cookies/`localStorage` across runs (`.hyperagent/storage_state.json`) via **Save login** / **Use saved login session**, and configure a local **Operator Profile** (`Profile` modal) for zero-typing form autofill. |
| **Parallel Multi-Tab Research & Self-Improving Domain Memory** | `read_urls_parallel` opens and extracts up to 4 `http(s)` URLs concurrently in background tabs without stealing focus. Successful runs automatically distill concise domain workflow hints into `.hyperagent/domain_memory.json`. |
| **Clean Final Result & Run-to-Run Table Diff** | Produces a verified Markdown summary, sortable data table, one-click **Diff vs previous run** (`New` row badges + `old → new` cell diffs), verified source links, open caveats, and **Copy MD / CSV / JSON** exports—plus a collapsible sidebar of saved chats. |

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
 │         └─ Claude Haiku: Micro-prompt text value (TYPE_TEXT) │
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
   - Two failures of the same action on the same named control/page pause for operator guidance, across changed observation IDs, scrolls, reloads and planner/Jev handoffs. Resume resets the failure budget. Successful control execution clears its failures; returning from a failed delegation does not.
   - Page-state hashing (`_mark_no_change`), action-signature warnings (`_loop_warnings`), and CAPTCHA/bot-wall detection (`_page_warnings`) provide additional recovery signals. Click timeouts report whether another element intercepted the pointer, the control was disabled, or it was not visible/stable.
   - Every run—even if stopped early or out of steps/budget—synthesizes an honest partial `result` from saved `findings`.

---

## Verified Runs

**Stress test on 18 unseen goals** ([details and raw logs](docs/runs/stress-test/README.md)): research, tables, docs lookups, forms, logins, prices, flights, news, and pagination. On Claude Sonnet as planner, 16 of 18 complete end-to-end in 13–60 s; the remaining two end with an explicit partial report when blocked by a bot wall or insufficient upstream results.

**Dual system** (Planner + TypeSafe Jev):

| Task | Planner calls | Jev calls | Time | Planner cost | Outcome |
| --- | --- | --- | --- | --- | --- |
| Fill and submit the httpbin pizza order form, report what the server received | 6 | 7 (avg 434 ms) | 32 s | $0.0019 | Planner delegated phone, email, size, toppings, and delivery time to Jev (6 actions at 96–100% confidence), then requested operator approval on `"Submit order"`. |
| Delegate only (no planner): choose Large and tick Bacon and Mushroom | 0 | 4 | 3.4 s | n/a | 3 clicks plus `SUBGOAL_DONE` at 95–100% confidence; page state verified afterwards. |

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

Open **http://localhost:8766** (or set `PORT=8790` to run on another port).
- `/` opens the launcher; `/c/<chat-id>` opens a saved conversation. Back/Forward and direct-link refresh work in both the development server and the Python-served static build.
- After changing Python routes, restart the running backend on the same port. Rebuilding the frontend alone does not reload server routes; an older process may still return 404 on chat refresh.
- Chats and screenshots remain local to this browser. A chat URL does not share its data across devices. Leaving an active run stops it and saves its terminal result before switching conversations.
- **Browser settings** below the launcher composer contains Start URL, Keep logins, and approval mode.
- The run header shows current-task tokens. **Run details** (`⋯`) separates task usage, the sum of tasks in this chat, and all saved chats in this browser. Deleted chats and missing historical usage are excluded; these are local recorded totals, not account billing.
- Agent questions and their answers stay together inline in Live Stream. Completed steps get checkmarks, and the plan and action history start expanded.
- For frontend hot-reload during development: run `npm run dev` in `apps/web` (port 3000; connects to the backend on 8766).
- For offline UI testing without spending API credits: run `npm run mock` and `npm run dev:mock` in `apps/web`.
- CLI headless smoke runner:
  ```bash
  uv run --env-file .env python tools/run_task.py "On books.toscrape.com, list the Travel books with prices" --out run.json
  ```

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
              dom.js (reading-order DOM walker) · llm.py · tools.py · prompts.py · server.py
apps/web/     Next.js 15 console: AgentApp, Launcher, ControlBar, Timeline, StepCard,
              BrowserView, ApprovalCard, ResultsPanel, ResultReport, DataTable, OperatorModals
docs/         protocol.md (WebSocket contract) · runs/ (verified run logs & stress tests)
tests/        50 offline unit, agent, System 1, and real-Chromium integration tests
tools/        run_task.py live CLI runner
```

Run the full verification suite (no paid API calls):

```bash
uv run ruff check . && uv run pytest
cd apps/web && npm run lint && npm run typecheck && npm run build
```

Offline browser navigation checks (frontend running, all agent traffic intercepted):

```bash
CONSOLE_URL=http://localhost:3000 uv run pytest tests/test_console_ui.py -q
```
