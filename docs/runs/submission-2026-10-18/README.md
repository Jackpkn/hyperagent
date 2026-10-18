# Submission verification — 18 October 2026

Tested production code: `6af4136`, with the new eval tooling and documentation added in the submission commits.
No production backend or frontend code changed during these checks. [Structured evidence](evidence.json)
contains the live fixture verdicts, catalogue result, independent source readings, and recorded usage.

## Checks

- `uv run ruff check .`: passed.
- `uv run pytest -q`: **155 passed**, including real Chromium console, persistence, agent, Jev, and eval tests.
- Frontend `npm run lint`, `npm run typecheck`, `npm run build`: passed.
- Actual console at `localhost:8780`: connected to the configured backend and streamed **84 browser frames**
  during the catalogue run. No browser JavaScript exceptions or console errors were observed.
- The report table survived a real page reload unchanged. The document had no horizontal overflow at 1600px.
  Existing offline layout tests also exercise 1440px, 1000px, and 390px viewports.

## Live evals

Both used `claude-sonnet-5-5`, with Jev available, default risky-action approval, a 12-step limit,
120-second agent timeout, and a $0.25 tracked planner/extraction budget.

| Case | Independent verdict | Time | Browser actions | Step errors |
| --- | --- | ---: | ---: | ---: |
| Preserve a prefilled form | Pass | 16.247s | 3 | 0 |
| Commit an autocomplete selection | Pass | 15.855s | 3 | 0 |

The planner chose direct actions in both trials: **zero Jev calls**. Configuring Jev does not guarantee
delegation. These are one trial per case, not a success-rate estimate or a planner-versus-Jev comparison.

## Real catalogue task through the frontend

Goal entered into the actual launcher:

> Open https://books.toscrape.com/. In the Travel category, compare all listed books and identify the three
> cheapest by displayed price. Open each of those three books and verify its full title, price, stock count
> and UPC. Return a table sorted by price with source URLs. State how many Travel books you compared.
> Do not log in or buy anything.

The agent compared **11 books**, used five planner turns and four page extractions, and completed in
**41.8 seconds** of recorded agent time. The UI smoke, including rendering and refresh checks, took about
46 seconds. A separate browser visit read the entire category and each selected product page. All 18
requested table cells (three rows × title, price, stock, UPC, URL, and rank) were checked; rank follows the
independently sorted source prices. The comparison count also matched.

| Book | Price | Available | UPC |
| --- | ---: | ---: | --- |
| The Road to Little Dribbling: Adventures of an American in Britain (Notes From a Small Island #2) | £23.21 | 3 | 366a236aa1ea6f07 |
| 1,000 Places to See Before You Die | £26.08 | 1 | 228ba5e7577e1d49 |
| The Great Railway Bazaar | £30.54 | 6 | 48736df57e7bec9f |

Product URLs and complete results are retained in `evidence.json`. The site is a public demonstration
catalogue with synthetic prices; this trial does not establish reliability on arbitrary production sites.

## Live Jev form smoke

A separate explicit CLI run filled the public `https://httpbin.org/forms/post` demo with fictional contact
details, Medium size, Extra Cheese and Mushroom, delivery time 18:30, and a test-only instruction.
It stopped before submission. The agent disclosed that the site's cheese option is named Extra Cheese.

- Two planner calls; nine Jev calls (eight browser actions plus subgoal completion); five text-helper calls.
- About 25 seconds total; no action error in the recorded timeline.
- The action trace and final model report were inspected. Unlike the two local fixtures, this external
  form smoke has no separate outcome grader; do not count it as an independently graded pass.

## Limits and follow-up work

These checks found no errors in the exercised paths; they do not prove that every website or goal works.
Planner/extraction costs are recorded, but Jev/text-helper costs are missing from current totals.
The UI's token-savings indicator is a heuristic. No measured savings claim is made here.

Next priorities: repeated live trials, calendar and recovery evals, complete provider usage accounting,
and more testing against dynamic production sites. Public deployment checks follow the main-branch push.
