# Evaluator experience implementation plan

**Goal:** A new natural-language task should start autonomously, remain understandable and steerable, and end in a useful source-backed result or an explicit blocker.

**Architecture:** Extend the existing page → observed actions → one decision → one execution loop. Keep one session worker and two existing model roles. Add no agent hierarchy or site-specific workflow. Public deployment depends on the user's target account/project.

**Constraints:** Preserve existing work and credentials; no commits or pushes. No browser mutation retries. Tests never call paid APIs. Preserve HyperAgent internals; visible branding awaits the user's clarification.

- [x] Make `START.url` optional using a configurable general search entry page. Keep an optional website input in the console. Test missing goals, goal-only start and explicit URL precedence.
- [x] Publish plan, phase, actual action/page counts and completion criteria. Show a compact expandable task panel and current action, without invented milestone completion or extra inference calls.
- [x] Preserve observed anchor URLs with evidence. Reject unobserved URLs in synthesized records. Results show supporting quotes, executed actions and unresolved requirements; a failed verification can still expose clearly unverified partial findings.
- [x] Permit returning to an observed open tab, so a new tab does not strand the agent. Cover freshness and ownership in offline tests.
- [x] Add a generic bounded live benchmark runner and a scenario checklist covering research, forms, dynamic pages, tabs, failures and intervention. Record failures and distinguish live checks from offline tests.
- [x] Run required checks, a real robotics-research attempt and Chromium UI validation. Rebuild and check the local Docker service.
- [ ] Deploy publicly after the hosting target is supplied; no public URL has been provisioned.

Review focus: original intent survives guidance; no fabricated progress; observed links remain attributable; tab switching cannot target another session; unverified artifacts never masquerade as completion.

## Verification record — 2026-10-17

- Ruff and snapshot JavaScript syntax pass. Offline suite: 111 passed. Python wheel/sdist, frontend lint, typecheck and production build pass.
- Headless Chromium UI check: goal-only START, visible plan/counts, approval gate, partial results, source quotes, unresolved requirements and action history; no console errors or mobile horizontal overflow. WebSocket responses were stubbed for this UI test.
- Real Chromium transport check with temporary local pages: observed anchor URL, asynchronous popup adoption, and switching back to the original owned tab passed. No model calls in either check.
- Live robotics research attempt: 2 browser actions, 55 display frames, 5 policy decisions, 2 text-helper decisions, 1 recovery decision; paused after Mercury returned malformed JSON. No verified deliverable. Raw events and result: `artifacts/benchmarks/robotics-01/`. Counts are decisions, not total billed HTTP requests.
- Public deployment remains pending a hosting account/project. Existing HyperAgent branding retained pending clarification.

- Rebuilt Docker image and replaced only `hyperagent-local` at `http://localhost:8770`. Health, latest goal-first HTML and WebSocket pause/stop acknowledgements passed.
