# Jev default execution

Approved scope: default routine UI actions to Jev; skip satisfied controls; preserve approval,
password handling, latest-observation IDs, and text-only model inputs.

- [x] Add offline regression tests for routing, selected controls, opposite-state toggles,
  stale decisions, and mutation timeouts.
- [x] Surface selected/pressed/checked/disabled and exact field state; share no-op checks.
- [x] Give Jev separate activation/deactivation targets, excluding already-satisfied targets.
- [x] Route isolated planner UI actions to bounded Jev execution, preserving risk intent.
  Allow one explicitly visible planner recovery after Jev fails or is unsure.
- [x] Recheck state and operator guidance before executing; remove automatic mutation fallbacks.
- [x] Run required checks, document behavior, rebuild, and restart the local backend.

Validation: Ruff passed; pytest 103 passed with 8 UI checks initially skipped, then all
8 UI checks passed with CONSOLE_URL=http://localhost:8780 and mocked model connections.
Frontend lint, typecheck and production build passed. Backend restarted on port 8780.

No paid API calls, commits, or pushes. Existing workspace changes remain intact.
