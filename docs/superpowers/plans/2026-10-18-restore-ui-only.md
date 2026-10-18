# Restore the accepted console design, frontend only

The user requests the earlier sidebar and layout, asks for a careful plan and subagent execution, and explicitly forbids backend changes. Prior conversation approves the design below; this is restoration, not a new product design.

## Global constraints

- Do not modify any file under `hyperagent/`, any server/event protocol, `next.config.ts`, model configuration, agent reducer, browser automation, persistence hooks, or token accounting.
- Preserve the existing uncommitted refresh fix byte-for-byte in `PastTurns.tsx`, `use-chats.ts`, `chat-model.ts`, and `tests/test_chat_refresh.py`.
- Preserve `tokens.css` and the current light/dark colors. Do not touch the existing `.globals.css.swp`.
- No commits, pushes, dependencies, paid model calls, live purchases, or additional subagent spawning by workers.
- Use current callbacks to open saved chats and operate controls. Do not restore `/c/:id` routes: those require a backend fallback and exceed this UI-only request.
- Earlier user-requested example cards are permitted as launcher suggestions; do not add site-specific backend flows.

## Task 1: Restore the presentation and integrate existing callbacks

Read README.md and apps/web/AGENTS.md. Treat `e57c9e3` as visual reference only; never cherry-pick it wholesale. The current working tree already passes 86 tests, lint, typecheck, and build.

Allowed product files:
- `apps/web/src/components/Launcher.tsx`
- `apps/web/src/components/BrowserSettings.tsx` (new)
- `apps/web/src/components/ChatSidebar.tsx` (new)
- `apps/web/src/components/AgentApp.tsx`
- `apps/web/src/components/ControlBar.tsx`
- `apps/web/src/styles/launcher.css`, `components.css`, `run.css` (only necessary layout rules)
- `apps/web/src/app/layout.tsx`, `apps/web/public/hyperagent-icon.svg`

Requirements:
1. Collapsible left sidebar on launcher and chat workspace, with New task, saved chats, active indication, delete, Autofill profile, and Memory. Chat clicks use existing openChat; no drawer or route changes. Sidebar navigation uses buttons, not links to nonexistent routes. Avoid duplicate top-bar profile/memory/chat controls. Preserve existing behavior when switching away from an active run.
2. Launcher centered in remaining space; recover previous compact width (900px content target, never wider than 1000px), responsive on small screens. Composer and card grid share aligned edges. Keep heading, remove Autonomous Browser Operator / Live Multimodal Execution badge. Neutral textarea focus border with accessible keyboard focus.
3. Four actual prompt cards below composer: Research, Data, Workflow, Explore, using previous accepted prompts in e57c9e3. Cards insert editable text only; never auto-start. All prompt text visible, no dropdown. Two-column grid desktop, one column mobile.
4. Model selector and Start agent stay in composer. One Browser settings disclosure below composer holds Start URL, Keep logins, and existing approval options. Keep labels and semantics; keyboard Escape closes and returns focus; invalid hidden URL field must open for correction. Preserve exact StartOptions fields and existing callbacks.
5. Run header retains title/status/goal, steps/time/cost, approval selector, pause/resume/stop, connection in a SINGLE row on desktop. Compact Fast details via existing values/title if needed, no new accounting. Narrow screens can horizontally scroll controls instead of hiding them or making a second metrics strip. Preserve existing confirmation and control semantics; do not alter GuidanceComposer behavior.
6. Restore the existing HyperAgent SVG favicon through layout metadata.

Verification:
- Add `tests/test_console_design.py` using the real built frontend, local fixture WebSocket data, and real IndexedDB, following tests/test_chat_refresh.py. No paid APIs. Cover sidebar opening saved chats, New task, settings payload unchanged, example inserts without starting, narrow viewport overflow/control reachability, and desktop single-row controls. Do not add tests that only grep source.
- Run npm lint/typecheck/build; run focused design and refresh tests. Capture launcher and populated workspace screenshots at desktop and mobile in `/private/tmp/hyperagent-ui-restore-20261018/` for controller visual review.
- Report files changed, test commands/results, screenshot paths, concerns to `/private/tmp/hyperagent-ui-restore-20261018/task-1-report.md`.

## Task 2: Independent review and final verification

Controller packages diff against the baseline into a review file. Independent reviewer checks scope, existing callback behavior, refresh fix preservation, responsive layout and accessibility against Task 1. Reviewer does not edit or repeat passing tests. Implementer resolves material findings and reviewer checks the scoped fix.

Controller checks protected file hashes, runs `uv run ruff check .`, `uv run pytest`, and frontend lint/typecheck/build as needed after final changes. Inspect screenshots and confirm localhost:8780 serves the rebuilt frontend. Leave changes uncommitted.

## Execution record

- Baseline: 041c78a plus the tested refresh fix; backup and protected SHA-256 manifest in `/private/tmp/hyperagent-ui-restore-20261018/`.
- Existing design approval and the user's explicit instruction to plan and execute authorize this bounded restoration. Work in the existing checkout with a snapshot; preserve all current work.
- Task 1 completed by implementation subagent; six design checks and four refresh checks passed. Desktop/mobile screenshots reviewed.
- Task 2 completed by independent review subagent: approved with no material findings. Full suite: 92 passed; Ruff, frontend lint, typecheck and build passed. All 23 protected hashes unchanged. Localhost:8780 serves the exact rebuilt index and favicon. No commits or pushes.
