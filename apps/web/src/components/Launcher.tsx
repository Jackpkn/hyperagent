"use client";

import { useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  BookmarkCheck,
  Bot,
  Compass,
  Globe,
  Brain,
  MessagesSquare,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  UserCheck,
  Zap,
} from "lucide-react";
import type { ApprovalMode } from "@/lib/protocol";
import type { StartOptions } from "@/lib/use-agent";

interface LauncherProps {
  connected: boolean;
  models: readonly string[];
  defaultModel: string;
  fastModel?: string | null;
  persistSession: boolean;
  hasSavedSession?: boolean;
  hasProfileData: boolean;
  historyCount: number;
  memoryCount: number;
  onTogglePersistSession: () => void;
  onClearSavedSession: () => void;
  onOpenProfile: () => void;
  onOpenHistory: () => void;
  onOpenMemory: () => void;
  onStart: (options: StartOptions) => boolean;
}

interface PresetTask {
  readonly title: string;
  readonly badge: string;
  readonly startUrl: string;
  readonly summary: string;
  readonly goal: string;
}

const PRESET_TASKS: readonly PresetTask[] = [
  {
    title: "Product Specs & Price Matrix",
    badge: "Research",
    startUrl: "https://www.rtings.com/headphones",
    summary: "Extract ANC score, battery life, comfort rating, and price into a verified matrix.",
    goal: "Navigate to RTINGS or Wirecutter, research the top 3 wireless noise-cancelling headphones currently recommended, extract their active noise isolation score, tested battery life, and price into a comparison matrix with source citations.",
  },
  {
    title: "Catalog Filter & Extraction",
    badge: "Workflow",
    startUrl: "https://books.toscrape.com",
    summary: "Filter Fiction books with 4+ stars under £20, extracting titles, star ratings, and stock counts.",
    goal: "Navigate to Books to Scrape, filter for Fiction books that have a 4 or 5-star rating priced under £20. Extract title, star rating, price, and in-stock count for each, normalizing the data into a clean table.",
  },
  {
    title: "AI Sentiment & Consensus Brief",
    badge: "Synthesis",
    startUrl: "https://news.ycombinator.com",
    summary: "Scan top trending AI discussions, extract key technical arguments, and synthesize an executive brief.",
    goal: "Scan today's top stories on Hacker News for the highest-voted AI or LLM discussions. Read the discussion threads, summarize the dominant community consensus and criticisms, and compile a structured executive brief with links.",
  },
];

const MODES: { value: ApprovalMode; label: string; short: string; detail: string }[] = [
  {
    value: "risky",
    label: "Ask before risky actions",
    short: "Risky actions",
    detail: "Pauses before submitting, buying, sending, or deleting.",
  },
  {
    value: "always",
    label: "Ask before every action",
    short: "Every action",
    detail: "You approve each click, typed value, and navigation.",
  },
  {
    value: "never",
    label: "Fully autonomous",
    short: "Autonomous",
    detail: "Runs to completion without asking for approval.",
  },
];

export function Launcher({
  connected,
  models,
  defaultModel,
  persistSession,
  hasSavedSession,
  hasProfileData,
  historyCount,
  memoryCount,
  onTogglePersistSession,
  onClearSavedSession,
  onOpenProfile,
  onOpenHistory,
  onOpenMemory,
  onStart,
}: LauncherProps) {
  const [goal, setGoal] = useState("");
  const [startUrl, setStartUrl] = useState("");
  const [showUrlInput, setShowUrlInput] = useState(false);
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
        <div className="launch-badge">
          <Sparkles size={13} aria-hidden="true" />
          <span>Autonomous Browser Operator</span>
          <span className="launch-badge-dot" aria-hidden="true" />
          <span className="launch-badge-sub">Live Multimodal Execution</span>
        </div>
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
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) submit();
            }}
            placeholder="Describe what you want done in the browser, in plain English…"
            rows={4}
          />

          {showUrlInput || startUrl ? (
            <div className="composer-url-row">
              <Globe size={14} className="composer-url-icon" aria-hidden="true" />
              <label htmlFor="start-url" className="sr-only">
                Start at a URL (optional)
              </label>
              <input
                id="start-url"
                className="composer-url-input mono"
                type="url"
                inputMode="url"
                value={startUrl}
                onChange={(event) => setStartUrl(event.target.value)}
                placeholder="https:// (optional starting URL)"
                autoComplete="off"
              />
            </div>
          ) : null}

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

              <button
                type="button"
                className={`composer-pill composer-btn-pill${showUrlInput || startUrl ? " is-active" : ""}`}
                onClick={() => setShowUrlInput((prev) => !prev)}
                title="Set an optional starting URL"
              >
                <Globe size={13} aria-hidden="true" />
                <span>{startUrl ? "Start URL set" : "Start URL"}</span>
              </button>

              <button
                type="button"
                className={`composer-pill composer-btn-pill${persistSession ? " is-active" : ""}`}
                onClick={onTogglePersistSession}
                title="Persist browser login cookies and storage across runs"
              >
                <BookmarkCheck size={13} aria-hidden="true" />
                <span>{persistSession ? "Logins saved" : "Keep logins"}</span>
                {hasSavedSession ? <span className="dot dot-open" aria-hidden="true" /> : null}
              </button>

              {hasSavedSession ? (
                <button
                  type="button"
                  className="composer-pill composer-btn-pill"
                  onClick={onClearSavedSession}
                  title="Clear saved browser login cookies"
                >
                  <span>Clear cookies</span>
                </button>
              ) : null}

              <button
                type="button"
                className={`composer-pill composer-btn-pill${hasProfileData ? " is-active" : ""}`}
                onClick={onOpenProfile}
                title="Set reusable autofill profile (name, email, address, preferences)"
              >
                <UserCheck size={13} aria-hidden="true" />
                <span>{hasProfileData ? "Profile active" : "Autofill profile"}</span>
              </button>

              <button
                type="button"
                className={`composer-pill composer-btn-pill${memoryCount > 0 ? " is-active" : ""}`}
                onClick={onOpenMemory}
                title="What the agent remembers about you across chats"
              >
                <Brain size={13} aria-hidden="true" />
                <span>{memoryCount > 0 ? `Memory (${memoryCount})` : "Memory"}</span>
              </button>

              {historyCount > 0 ? (
                <button
                  type="button"
                  className="composer-pill composer-btn-pill"
                  onClick={onOpenHistory}
                  title="Your saved chats in this browser"
                >
                  <MessagesSquare size={13} aria-hidden="true" />
                  <span>Chats ({historyCount})</span>
                </button>
              ) : null}
            </div>

            <div className="composer-submit-group">
              <span className="hint composer-shortcut">⌘ + Enter</span>
              <button type="submit" className="btn btn-primary" disabled={!canStart}>
                <span>Start agent</span>
                <ArrowRight size={15} aria-hidden="true" />
              </button>
            </div>
          </div>
        </div>

        {!connected ? (
          <p className="hint" role="status" style={{ marginTop: 8, textAlign: "center" }}>
            Connecting to the agent server… You can write your goal now and start once connected.
          </p>
        ) : null}
      </form>

      <section className="starter-presets" aria-labelledby="starter-presets-heading">
        <div className="starter-presets-header">
          <Compass size={13} className="starter-presets-icon" aria-hidden="true" />
          <span id="starter-presets-heading">One-Click Showcase Workflows</span>
        </div>
        <div className="starter-grid">
          {PRESET_TASKS.map((preset) => {
            const isSelected = goal.trim() === preset.goal.trim();
            let domain = "";
            try {
              domain = new URL(preset.startUrl).hostname.replace(/^www\./, "");
            } catch {
              domain = preset.startUrl;
            }
            return (
              <button
                key={preset.title}
                type="button"
                className={`starter-card${isSelected ? " is-selected" : ""}`}
                onClick={() => {
                  setGoal(preset.goal);
                  setStartUrl(preset.startUrl);
                  setShowUrlInput(true);
                }}
                title={`Load workflow: ${preset.title}`}
              >
                <div className="starter-card-top">
                  <span className="starter-tag">{preset.badge}</span>
                  <div className="starter-meta">
                    <span className="starter-domain">{domain}</span>
                    <ArrowUpRight size={12} className="starter-arrow" aria-hidden="true" />
                  </div>
                </div>
                <h3 className="starter-card-title">{preset.title}</h3>
                <p className="starter-card-desc">{preset.summary}</p>
              </button>
            );
          })}
        </div>
      </section>

      <fieldset className="mode-group" aria-label="Approval policy">
        <legend className="sr-only">How much should the agent check with you?</legend>
        {MODES.map((option) => (
          <label key={option.value} className="mode-option">
            <input
              type="radio"
              name="approval-mode"
              value={option.value}
              checked={mode === option.value}
              onChange={() => setMode(option.value)}
            />
            <div className="mode-option-head">
              {option.value === "risky" ? (
                <ShieldCheck size={15} className="mode-card-icon" aria-hidden="true" />
              ) : option.value === "always" ? (
                <ShieldAlert size={15} className="mode-card-icon" aria-hidden="true" />
              ) : (
                <Zap size={15} className="mode-card-icon" aria-hidden="true" />
              )}
              <strong>{option.label}</strong>
            </div>
            <span>{option.detail}</span>
          </label>
        ))}
      </fieldset>
    </section>
  );
}
