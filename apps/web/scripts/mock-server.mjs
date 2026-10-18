// Mock HyperAgent backend for UI development. It speaks docs/protocol.md and
// replays a plausible run: navigation, a recovered error, a question, a risky
// step that waits for approval, live findings, usage and a final result.
//
//   npm run mock           (listens on MOCK_PORT, default 8799)
//   NEXT_PUBLIC_WS_URL=ws://localhost:8799/ws/agent npm run dev
//
// Port 8766 is intentionally not the default: it may belong to another process.

import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { WebSocketServer } from "ws";

const PORT = Number(process.env.MOCK_PORT ?? 8799);
const HERE = dirname(fileURLToPath(import.meta.url));
const MODELS = ["mock-fast", "mock-strong"];
const MAX_STEPS = 30;
const STOPPED = Symbol("stopped");

const FRAMES = [
  { file: "frame-1.jpg", url: "https://books.toscrape.com/", title: "Books to Scrape" },
  { file: "frame-2.jpg", url: "https://books.toscrape.com/catalogue/category/books/travel_2/index.html", title: "Travel | Books to Scrape" },
  { file: "frame-3.jpg", url: "https://httpbin.org/forms/post", title: "httpbin forms" },
].map((frame) => ({
  ...frame,
  image: readFileSync(join(HERE, "mock-frames", frame.file)).toString("base64"),
}));

const FINDINGS = [
  { title: "A Light in the Attic", price: "£51.77", rating: "Three stars", availability: "In stock" },
  { title: "Tipping the Velvet", price: "£53.74", rating: "One star", availability: "In stock" },
  { title: "Soumission", price: "£50.10", rating: "One star", availability: "In stock" },
  { title: "Sharp Objects", price: "£47.82", rating: "Four stars", availability: "In stock" },
  { title: "Sapiens", price: "£54.23", rating: "Five stars", availability: "Out of stock" },
  { title: "The Requiem Red", price: "£22.65", rating: "One star", availability: "In stock" },
];

class MockRun {
  constructor(ws, { goal, startUrl, mode }) {
    this.ws = ws;
    this.goal = goal;
    this.startUrl = startUrl;
    this.mode = mode;
    this.paused = false;
    this.stopped = false;
    this.resumeWaiters = [];
    this.decisions = new Map(); // step_id -> { approve, reason }
    this.guidanceWaiter = null;
    this.records = new Map();
    this.plan = [];
    this.findings = [];
    this.frameIndex = 0;
    this.finished = false;
    this.llmCalls = 0;
    this.cost = 0;
    this.startedAt = Date.now() / 1000;
    this.stepCounter = 0;
    this.timers = [];
    this.timers.push(setInterval(() => this.sendFrame(), 400));
    this.timers.push(setInterval(() => this.sendUsage(), 1000));
  }

  send(message) {
    if (this.ws.readyState === this.ws.OPEN) this.ws.send(JSON.stringify(message));
  }

  setStatus(state, detail) {
    this.send({ type: "status", state, step: this.stepCounter, detail });
  }

  sendFrame() {
    const frame = FRAMES[this.frameIndex % FRAMES.length];
    this.send({
      type: "frame",
      image: frame.image,
      url: frame.url,
      title: frame.title,
      w: 1280,
      h: 800,
      tabs: [
        { index: 0, title: "Books to Scrape", url: "https://books.toscrape.com/", active: this.frameIndex % FRAMES.length === 0 },
        { index: 1, title: frame.title, url: frame.url, active: this.frameIndex % FRAMES.length !== 0 },
      ],
    });
  }

  sendUsage() {
    if (this.stopped || this.finished) return;
    if (!this.paused) this.cost += 0.0021;
    this.send({
      type: "usage",
      llm_calls: this.llmCalls,
      input_tokens: this.llmCalls * 5400,
      output_tokens: this.llmCalls * 380,
      cost_usd: Number(this.cost.toFixed(4)),
      elapsed_s: Number((Date.now() / 1000 - this.startedAt).toFixed(1)),
    });
  }

  emitPlan(statuses) {
    this.plan = this.plan.map((item, i) => ({ text: item.text, status: statuses[i] ?? item.status }));
    this.send({ type: "plan", items: this.plan });
  }

  emitStep(record) {
    this.records.set(record.id, record);
    this.send({ type: "step", ...record });
  }

  // Wait between actions. Honors pause and stop.
  async sleep(ms) {
    await new Promise((resolve) => setTimeout(resolve, ms));
    await this.checkpoint();
  }

  async checkpoint() {
    while (this.paused && !this.stopped) {
      await new Promise((resolve) => this.resumeWaiters.push(resolve));
    }
    if (this.stopped) throw STOPPED;
  }

  pause() {
    if (this.paused || this.stopped) return;
    this.paused = true;
    this.setStatus("paused", "Paused after the current action");
  }

  resume() {
    if (!this.paused) return;
    this.paused = false;
    this.resumeWaiters.splice(0).forEach((resolve) => resolve());
    this.setStatus("running", "");
  }

  stop() {
    this.stopped = true;
    this.paused = false;
    this.resumeWaiters.splice(0).forEach((resolve) => resolve());
    this.decisions.forEach((resolver) => resolver({ approve: false, reason: "stopped" }));
    this.decisions.clear();
    this.guidanceWaiter?.(null);
  }

  decide(stepId, approve, reason) {
    const resolver = this.decisions.get(stepId);
    if (!resolver) return false;
    this.decisions.delete(stepId);
    resolver({ approve, reason });
    return true;
  }

  // Creates a step, shows the model thinking, then records its decision.
  async think(label, next, evaluation, memory, action, target, risk) {
    this.stepCounter += 1;
    const id = `s${this.stepCounter}`;
    const started = Date.now() / 1000;
    this.llmCalls += 1;
    this.setStatus("thinking", "Deciding the next move");
    this.emitStep({ id, n: this.stepCounter, status: "thinking", started_at: started });
    await this.sleep(1100);
    const record = {
      id,
      n: this.stepCounter,
      status: "planned",
      thought: { evaluation, memory, next_goal: next },
      action: { name: action.name, args: action.args ?? {}, label },
      target,
      risk,
      started_at: started,
    };
    this.emitStep(record);
    return record;
  }

  // Runs an action. Risky steps wait for the operator when the mode asks.
  async act(record, { ms = 900, url, frameIndex, result, error, awaitInput }) {
    const needsApproval =
      this.mode === "always" || (this.mode === "risky" && record.risk?.risky);
    if (needsApproval) {
      this.emitStep({ ...record, status: "awaiting_approval" });
      this.send({
        type: "approval",
        step_id: record.id,
        reason: record.risk?.reason ?? "This action changes data on the site.",
        action_label: record.action.label,
        target_label: record.target?.label,
        args: record.action.args,
      });
      this.setStatus("awaiting_approval", "Waiting for you");
      const decision = await new Promise((resolve) => this.decisions.set(record.id, resolve));
      await this.checkpoint();
      if (!decision.approve) {
        this.emitStep({ ...record, status: "rejected", result: decision.reason ? `Skipped: ${decision.reason}` : "Skipped at your request", ended_at: Date.now() / 1000 });
        this.send({ type: "notice", level: "info", message: "Skipped that step as you asked." });
        return false;
      }
    }
    this.setStatus("acting", record.action.label);
    this.emitStep({ ...record, status: "running" });
    await this.sleep(ms);
    if (awaitInput) await awaitInput();
    if (frameIndex !== undefined) this.frameIndex = frameIndex;
    if (error) {
      this.emitStep({ ...record, status: "error", error, ended_at: Date.now() / 1000 });
      return false;
    }
    this.emitStep({ ...record, status: "ok", url: url ?? record.url, result, ended_at: Date.now() / 1000 });
    return true;
  }

  async askUser(question) {
    this.setStatus("awaiting_user", "The agent needs your answer");
    this.send({ type: "question", step_id: `s${this.stepCounter}`, question });
    const answer = await new Promise((resolve) => {
      this.guidanceWaiter = resolve;
    });
    this.guidanceWaiter = null;
    await this.checkpoint();
    return answer;
  }

  guide(text) {
    this.send({ type: "notice", level: "info", message: `Guidance received: "${text}". Applying it to the next decision.` });
    if (this.guidanceWaiter) this.guidanceWaiter(text);
  }

  async execute() {
    this.plan = [
      { text: "Open the book catalogue", status: "active" },
      { text: "Open the Travel category", status: "pending" },
      { text: "Collect every book on the listing", status: "pending" },
      { text: "Check the next page and wrap up", status: "pending" },
    ];
    this.setStatus("starting", "Opening a browser");
    await this.sleep(700);
    this.setStatus("running", "");
    this.send({ type: "plan", items: this.plan });

    const open = await this.think(
      'Open "https://books.toscrape.com"',
      "Load the catalogue home page",
      "This is the first step; nothing has been opened yet.",
      "Goal: Travel books with price, rating and stock.",
      { name: "navigate", args: { url: "https://books.toscrape.com" } },
      undefined,
      { risky: false, reason: "" },
    );
    await this.act(open, { url: FRAMES[0].url, frameIndex: 0, result: "Catalogue home page loaded" });
    this.emitPlan(["done", "active", "pending", "pending"]);

    const travel = await this.think(
      'Click "Travel"',
      "Open the Travel category listing",
      "The home page is loaded and shows category links in the sidebar.",
      "Catalogue home page is open.",
      { name: "click", args: { index: 14 } },
      { label: "Travel category link", rect: { x: 60, y: 430, w: 150, h: 26 } },
      { risky: false, reason: "" },
    );
    await this.act(travel, { url: FRAMES[1].url, frameIndex: 1, result: "Travel category: 11 books on this page" });

    const read = await this.think(
      "Read every book on the listing",
      "Record title, price, rating and stock",
      "The category page lists 11 books.",
      "Travel category is open; 11 books listed.",
      { name: "extract", args: { scope: "listing" } },
      undefined,
      { risky: false, reason: "" },
    );
    await this.act(read, { result: "Recorded 3 books so far" });
    this.findings = FINDINGS.slice(0, 3).map((data) => ({ source_url: FRAMES[1].url, data }));
    this.send({ type: "findings", items: this.findings });
    this.emitPlan(["done", "done", "active", "pending"]);

    const next = await this.think(
      'Click "Next"',
      "Move to the second page of Travel books",
      "Three of eleven books recorded; the page has a Next link.",
      "Recorded 3 books. Need the rest.",
      { name: "click", args: { index: 31 } },
      { label: "Next page link", rect: { x: 560, y: 690, w: 110, h: 28 } },
      { risky: false, reason: "" },
    );
    const clickedNext = await this.act(next, {
      error: "A cookie banner covers the Next link, so the click did not land.",
    });
    if (!clickedNext) {
      this.send({ type: "notice", level: "warn", message: "Recovering: closing the cookie banner and trying again." });
    }

    const dismiss = await this.think(
      'Click "Accept" on the cookie banner',
      "Clear the banner so the Next link is reachable",
      "The banner is on top of the page controls; it is safe to dismiss.",
      "Next click was blocked by the cookie banner.",
      { name: "click", args: { index: 2 } },
      { label: "Cookie banner: Accept", rect: { x: 900, y: 600, w: 120, h: 32 } },
      { risky: false, reason: "" },
    );
    await this.act(dismiss, { result: "Banner dismissed" });

    const question = await this.think(
      "Ask whether to include sold-out books",
      "Confirm what the list should include",
      "One book is out of stock. The goal does not say whether to include it.",
      "Recorded 4 books; one is sold out.",
      { name: "ask_user", args: { question: "Include sold-out books in the table?" } },
      undefined,
      { risky: false, reason: "" },
    );
    const answer = await this.askUser("Include sold-out books in the table?");
    if (answer === null) throw STOPPED;
    question.status = "planned";
    await this.act(
      { ...question, action: { ...question.action, label: `Answered: ${answer}` } },
      { result: `Using your answer: ${answer}` },
    );

    this.findings = FINDINGS.slice(0, 5).map((data) => ({ source_url: FRAMES[1].url, data }));
    this.send({ type: "findings", items: this.findings });
    this.emitPlan(["done", "done", "done", "active"]);

    const submit = await this.think(
      'Click "Submit" on the search form',
      "Submit the form to load the full results",
      "The filter form is ready to submit.",
      "Answer recorded; filters ready.",
      { name: "click", args: { index: 40 } },
      { label: "Submit search", rect: { x: 300, y: 510, w: 120, h: 34 } },
      { risky: true, reason: "Submitting a form sends a request to the site." },
    );
    const submitted = await this.act(submit, { frameIndex: 2, result: "Results loaded" });
    if (!submitted) {
      this.send({ type: "notice", level: "info", message: "Continuing with the books already collected." });
    }

    this.emitPlan(["done", "done", "done", "done"]);
    this.findings = FINDINGS.map((data) => ({ source_url: FRAMES[1].url, data }));
    this.send({ type: "findings", items: this.findings });
    await this.sleep(500);
    this.sendFinalResult(true);
  }

  sendFinalResult(success) {
    const rows = this.findings.map((finding) => finding.data);
    const summary = success
      ? `## Travel books on books.toscrape.com\n\nI collected **${rows.length} books** from the Travel category.\n\n- Prices are in GBP and were read from the listing.\n- Ratings are the star words shown on each card.\n- \`availability\` is copied from the product card.\n\nOne book, *Sapiens*, is out of stock.`
      : `## Partial result\n\nYou stopped the run. These **${rows.length} books** were collected before that.`;
    this.send({
      type: "result",
      success,
      summary,
      columns: ["title", "price", "rating", "availability"],
      rows,
      sources: [{ title: "Travel | Books to Scrape", url: FRAMES[1].url }],
      issues: success ? ["Only page 1 of the category was checked. More books may exist on later pages."] : ["Run stopped before the second page was checked."],
      checklist: [
        { requirement: "Open the Travel category", met: true, evidence: "Travel listing loaded", step_id: "s2", step_n: 2 },
        { requirement: "Collect title, price, rating and availability", met: success, evidence: success ? "Saved from the listing cards" : "Stopped before every book was saved", step_id: "s3", step_n: 3 },
      ],
      assumptions: ["Prices are as listed on the site, in GBP."],
      follow_ups: success ? ["Check page 2 of the Travel category", "Compare these with the Mystery category"] : [],
    });
    this.finish(success ? "done" : "stopped", success ? "Report written" : "Stopped at your request");
  }

  finish(state, detail) {
    this.finished = true;
    this.sendUsage();
    this.setStatus(state, detail);
    this.dispose();
  }

  dispose() {
    this.timers.forEach((timer) => clearInterval(timer));
    this.timers = [];
  }

  async start() {
    try {
      await this.execute();
    } catch (error) {
      if (error === STOPPED) {
        this.sendFinalResult(false);
        return;
      }
      this.dispose();
      this.send({ type: "notice", level: "error", message: `Mock run failed: ${String(error)}` });
      this.finish("failed", "Something went wrong");
    }
  }
}

const wss = new WebSocketServer({ port: PORT, path: "/ws/agent" });
console.log(`[mock] HyperAgent mock listening on ws://localhost:${PORT}/ws/agent`);

wss.on("connection", (ws) => {
  const send = (message) => ws.send(JSON.stringify(message));
  let run = null;
  send({ type: "hello", session_id: randomUUID(), model: MODELS[1], models: MODELS, max_steps: MAX_STEPS });

  ws.on("message", (raw) => {
    let message;
    try {
      message = JSON.parse(String(raw));
    } catch {
      return;
    }
    const active = run && !run.finished;
    switch (message.type) {
      case "start":
        if (active) {
          send({ type: "notice", level: "error", message: "A run is already in progress on this connection." });
          return;
        }
        run = new MockRun(ws, {
          goal: message.goal,
          startUrl: message.start_url,
          mode: message.approval_mode ?? "risky",
        });
        run.start();
        return;
      case "pause":
        run?.pause();
        return;
      case "resume":
        run?.resume();
        return;
      case "stop":
        if (active) {
          run.stop();
        }
        return;
      case "guide":
        if (active) run.guide(String(message.text));
        return;
      case "approve":
        if (active && !run.decide(message.step_id, true)) {
          send({ type: "notice", level: "warn", message: "Nothing is waiting on that step any more." });
        }
        return;
      case "reject":
        if (active) run.decide(message.step_id, false, message.reason);
        return;
      case "set_mode":
        if (run) run.mode = message.approval_mode;
        send({ type: "notice", level: "info", message: `Approval mode set to ${message.approval_mode}.` });
        return;
      case "takeover_click":
      case "takeover_type":
      case "takeover_scroll":
        if (run?.paused) {
          console.log("[mock] takeover", JSON.stringify(message));
          send({ type: "notice", level: "info", message: "Your input was sent to the page." });
        }
        return;
      default:
        return;
    }
  });

  ws.on("close", () => {
    if (run) run.dispose();
  });
});
