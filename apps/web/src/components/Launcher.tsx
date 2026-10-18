"use client";

import { useState } from "react";
import {
  ArrowRight,
  Bot,
  Compass,
} from "lucide-react";
import { BrowserSettings } from "./BrowserSettings";
import type { ApprovalMode } from "@/lib/protocol";
import type { StartOptions } from "@/lib/use-agent";

interface LauncherProps {
  connected: boolean;
  models: readonly string[];
  defaultModel: string;
  fastModel?: string | null;
  persistSession: boolean;
  hasSavedSession?: boolean;
  onTogglePersistSession: () => void;
  onClearSavedSession: () => void;
  onStart: (options: StartOptions) => boolean;
}

interface TaskExample {
  readonly title: string;
  readonly badge: string;
  readonly summary: string;
}

const TASK_EXAMPLES: readonly TaskExample[] = [
  {
    title: "Compare tools for my team",
    badge: "Research",
    summary: "Compare Linear, Asana, and ClickUp for a 10-person product team using their official sites. Create a brief with USD pricing, billing terms, key features, and limitations. Recommend the best fit and link your sources.",
  },
  {
    title: "Build a startup shortlist",
    badge: "Data",
    summary: "Find 10 developer-tool startups in Y Combinator’s company directory. Open each profile and build a clean table with company, batch, location, product summary, and website. Link each profile and mark missing details as unknown.",
  },
  {
    title: "Triage a GitHub backlog",
    badge: "Workflow",
    summary: "Review the 10 newest open bug reports in vercel/next.js on GitHub. Read each report and its comments, flag possible duplicates, and suggest a priority with a reason. Prepare a linked triage table and draft replies for reports missing reproduction steps.",
  },
  {
    title: "Turn complaints into product ideas",
    badge: "Explore",
    summary: "Find 5 Ask HN discussions about frustrating everyday software tasks. Read the comments, group recurring problems, and propose 3 small product ideas. For each, describe the user, a first version, and existing alternatives, with links to supporting comments.",
  },
];

export function Launcher({
  connected,
  models,
  defaultModel,
  persistSession,
  hasSavedSession,
  onTogglePersistSession,
  onClearSavedSession,
  onStart,
}: LauncherProps) {
  const [goal, setGoal] = useState("");
  const [startUrl, setStartUrl] = useState("");
  const [mode, setMode] = useState<ApprovalMode>("risky");
  const [model, setModel] = useState(defaultModel);

  const selectedModel = models.includes(model) ? model : defaultModel;
  const canStart = connected && goal.trim().length > 0;

  const submit = () => {
    if (!canStart) return;
    onStart({ goal, startUrl, mode, model: selectedModel, persistSession });
  };

  return (
    <section className="launch" aria-labelledby="launch-title">
      <div className="launch-hero">
        <h1 id="launch-title" className="launch-title">
          What should the agent <em>get done</em> in the browser?
        </h1>
        <p className="launch-lede">
          Describe the outcome in plain English. Watch every action live in a full-side browser,
          guide or pause at any moment, and get a verified report.
        </p>
      </div>

      <form
        className="goal-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <div className="goal-box">
          <label htmlFor="goal" className="sr-only">
            Your goal
          </label>
          <textarea
            id="goal"
            className="goal-input"
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="Describe what you want done in the browser, in plain English…"
            rows={4}
          />

          <div className="goal-foot">
            <div className="composer-controls">
              <div className="composer-pill" title="Planner model (System 2)">
                <Bot size={13} aria-hidden="true" />
                <label htmlFor="model" className="sr-only">
                  Planner model (System 2)
                </label>
                <select
                  id="model"
                  className="composer-select"
                  value={selectedModel}
                  onChange={(event) => setModel(event.target.value)}
                  disabled={models.length === 0}
                >
                  {models.length === 0 ? (
                    <option value={defaultModel}>{defaultModel || "Default model"}</option>
                  ) : null}
                  {models.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="composer-submit-group">
              <button type="submit" className="btn btn-primary" disabled={!canStart}>
                <span>Start agent</span>
                <ArrowRight size={15} aria-hidden="true" />
              </button>
            </div>
          </div>
        </div>

        <div className="composer-settings-row">
          <BrowserSettings mode={mode} onModeChange={setMode} startUrl={startUrl} onStartUrlChange={setStartUrl}
            persistSession={persistSession} hasSavedSession={hasSavedSession}
            onTogglePersistSession={onTogglePersistSession} onClearSavedSession={onClearSavedSession} />
          <p className="hint composer-shortcut">⌘ + Enter</p>
        </div>

        {!connected ? (
          <p className="hint" role="status" style={{ marginTop: 8, textAlign: "center" }}>
            Connecting to the agent server… You can write your goal now and start once connected.
          </p>
        ) : null}
      </form>

      <section className="starter-examples" aria-labelledby="starter-examples-heading">
        <h2 id="starter-examples-heading" className="starter-examples-heading">
          <Compass size={13} className="starter-examples-icon" aria-hidden="true" />
          What can you delegate?
        </h2>
        <div className="starter-grid">
          {TASK_EXAMPLES.map((example) => (
            <button
              key={example.title}
              type="button"
              className={`starter-card${goal.trim() === example.summary ? " is-selected" : ""}`}
              onClick={() => {
                setGoal(example.summary);
                document.getElementById("goal")?.focus();
              }}
              aria-label={`Use example: ${example.title}`}
            >
              <span className="starter-tag">{example.badge}</span>
              <span className="starter-card-title">{example.title}</span>
              <span className="starter-card-desc">{example.summary}</span>
            </button>
          ))}
        </div>
      </section>
    </section>
  );
}
