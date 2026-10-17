# HyperAgent console cleanup implementation plan

**Goal:** Make the existing HyperAgent Next.js console operate on real browser sessions, without demo fixtures, task presets, simulated telemetry, or fabricated success.

**Architecture:** Keep `hyperagent` as the sole Python package and `apps/web` as the console. One WebSocket owns one agent and a serial worker; a separate receiver accepts controls while browser/model work runs. Keep the observed-element operation/target contract and text helper. A completion proposal requires a fresh observation and a separate evidence-based verification before success is shown.

**Tech stack:** Next.js 15.5.28/React/Tailwind/Motion/TanStack; FastAPI, Playwright with local headless Chromium or remote CDP, TypeSafe and Anthropic server-side.

**Constraints:** HyperAgent branding. No commits or pushes. Preserve existing in-progress work and `.git`. Retain offline engine tests. No paid API calls during checks. No hardcoded task fields. No browser mutation retries. Keep screenshots outside model input. No claims of production readiness or unmeasured speed.

## Tasks

- [x] Add regressions for indexed override validation, observation failure after mutation, Tabu filtering, false completion fallback, and session control/isolation. Observe failures before repair.
- [x] Repair engine adapters in `agent.py`, `model.py`, `supervisor.py`, and `claude_sys2.py`: stable observed indices, shared execution path, current goal constraints, explicit unavailable System 2, independent outcome verification.
- [x] Replace `server.py` global state and nested run loop with per-connection session workers. START, PAUSE, RESUME, STEP, WHISPER, SET_SLOWMO, OVERRIDE_CLICK, FORCE_EXTRACT and STOP share the same serialized execution and supervision. Manual clicks require paused state and the observed page fingerprint.
- [x] Remove the old demo server/static assets, demo recording scripts, task presets, alias package and unused scaffold assets. Preserve useful test coverage when removing examples. Point package entry points at FastAPI.
- [x] Wire the console to real WebSocket events, actual element rectangles and execution history. Use empty/disconnected/error states; no simulation fallback or fabricated probabilities. Replace the demo console with a new general-purpose console and accessible controls.
- [x] Update README, environment examples, package metadata and checks. Verify Python lint/tests/build, snapshot JavaScript syntax, frontend lint/types/build and a local browser smoke check if available.

## Review focus

- A client disconnect must close only its own browser, after any in-flight mutation finishes.
- Pause/Whisper received during inference must prevent outdated execution; mutations already in progress finish once.
- Unknown or stale element indices must never fall back to another element.
- Missing credentials, model errors, and DONE proposals must not produce false success.
- The screenshot and SVG overlay must share dimensions and observed geometry; navigation must update the shown URL.

## Deployment boundary

This pass provides a working operator console and isolated in-process sessions, not a hosted multi-tenant service. Public hosting requires authentication, network isolation, quotas and persistent session design. Remote CDP must use an actual transport, not just an environment-variable check.

## Verification record

67 offline tests pass. Python lint, snapshot syntax, frontend lint/typecheck/static export, and Python distributions pass. Local headless Chromium and local remote-CDP smoke checks cover typed input, click, select, geometry and ownership. Desktop/mobile UI checks cover interruption controls, observed override, guidance acknowledgment, unverified artifacts, filtering and JSON download; no browser console errors. No paid model calls. Production dependency audit is clean; five development-only ESLint dependency advisories remain. Docker daemon unavailable: image and hosted-provider deployment unverified. `.git` preserved; no commit or push.
