# Submission message

Hi,

Here's **HyperAgent**, my submission for the browser-agent challenge:

- **Live app:** https://hyperagent-lp95.onrender.com
- **Repository:** https://github.com/Jackpkn/hyperagent (private; reviewer access is required)

HyperAgent takes a plain-English goal and uses an LLM planner to navigate, read, click, extract, and fill
forms in a real browser. It can delegate focused UI work to TypeSafe Jev. The interface shows live browser
frames, action explanations, findings, and a structured final report. Users can pause, stop, steer the
agent, or approve risky actions.

For an end-to-end demo, ask it to compare the Travel books on Books to Scrape and return the three cheapest
with verified stock counts, UPCs, prices, and source URLs. In my latest test it compared 11 books and
completed in about 42 seconds. I independently checked the returned details against the source pages and
verified that the report survives a refresh. A separate live form test exercised eight delegated Jev
actions and stopped before submitting.

The project passes 155 automated tests plus frontend lint, typecheck, and build checks. I also added two
independent browser evals for preserving already-correct form fields and committing autocomplete
selections; both passed a live trial. The repository includes the evidence and known limitations.

With more time, I'd expand the eval suite to calendars and failure recovery, complete per-provider token
and cost accounting, and improve reliability across more dynamic sites. I'm happy to walk through the
architecture, UI decisions, and trade-offs on the call.

Best,
Pawan
