# Evaluator acceptance scenarios

These are validation scenarios, not task templates or runtime plans. Keep websites,
dates and instructions in the supplied goal; never encode their click sequence.

Run the app, then invoke `uv run python tools/benchmark.py --goal "..."`.
The runner uses the app's configured paid providers. Offline `pytest` never does.
Each output directory contains raw protocol events and a result summary, including
failed attempts. It stops at the first blocker, approval request or configured budget.

| Scenario | What counts as passing |
| --- | --- |
| Unfamiliar multi-site research: European robotics startups hiring engineers, with products, founders and application links | At least two distinct companies; geography, actual engineering openings, founders and products evidenced; application links copied from observed pages; missing facts explicitly unresolved. Independently inspect each final source. |
| Dynamic search form | Required fields, suggestions and dates visibly applied; submitted results match them. Filling a form alone is not success. |
| New-tab navigation | Open a real linked page, gather evidence, return to the original owned tab, and retain both sources in the result. |
| Navigation failure or loading page | Show the failure, observe before making another decision, avoid repeating uncertain mutations, and stop clearly when no supported path exists. |
| Human interruption | Pause during inference; no stale action executes. Add a constraint and resume without losing existing evidence. Stop closes only this session. |
| Sensitive operation | Review the exact target and text, reject it without input, then approve a fresh action once. Changed page/instructions invalidate approval. |
| Structured output with missing information | Emit a clearly unverified partial artifact with sources, executed actions and unresolved issues; never invent a missing price, founder, job or link. |

Record task-level success and interventions, not only successful clicks. Repeat across
different sites and instructions before reporting success rates, latency percentiles,
calibration or cost. A checked-in checklist is not proof that a scenario passed.
