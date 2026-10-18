"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import * as Collapsible from "@radix-ui/react-collapsible";
import {
  Activity,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  Clock,
  Coins,
  HelpCircle,
  MoreHorizontal,
  Pause,
  Play,
  Plus,
  Send,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Square,
  Zap,
} from "lucide-react";
import type { ApprovalMode, Question, RunState, Usage } from "@/lib/protocol";
import type { ConnectionState } from "@/lib/agent-state";
import { formatCost, formatDuration } from "@/lib/format";
import { totalTokens } from "@/lib/usage";

interface ControlBarProps {
  goal: string;
  run: RunState;
  hasResult?: boolean;
  detail: string;
  stepNumber: number;
  maxSteps: number;
  elapsedS: number;
  usage: Usage | null;
  chatUsage: Usage;
  allChatsUsage: Usage;
  mode: ApprovalMode;
  finished: boolean;
  connection: ConnectionState;
  reconnectAttempt: number;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
  onModeChange: (mode: ApprovalMode) => void;
  onNewTask: () => void;
}

const STATE_TEXT: Record<RunState, string> = {
  idle: "Ready",
  starting: "Starting browser",
  running: "Working",
  thinking: "Thinking",
  acting: "Acting on page",
  paused: "Paused",
  awaiting_approval: "Needs approval",
  awaiting_user: "Waiting for answer",
  finishing: "Writing report",
  done: "Completed",
  failed: "Stopped with error",
  stopped: "Stopped",
};

function toneFor(run: RunState, hasResult?: boolean): "live" | "wait" | "ok" | "error" | "idle" {
  switch (run) {
    case "done":
      return "ok";
    case "failed":
      return hasResult ? "wait" : "error";
    case "paused":
    case "awaiting_approval":
    case "awaiting_user":
      return "wait";
    case "stopped":
    case "idle":
      return "idle";
    default:
      return "live";
  }
}

const DOT_CLASS: Record<ReturnType<typeof toneFor>, string> = {
  live: "dot dot-live",
  wait: "dot dot-wait",
  ok: "dot dot-open",
  error: "dot dot-error",
  idle: "dot",
};

export function ControlBar(props: ControlBarProps) {
  const {
    goal,
    run,
    hasResult,
    detail,
    stepNumber,
    maxSteps,
    elapsedS,
    usage,
    chatUsage,
    allChatsUsage,
    mode,
    finished,
    connection,
    reconnectAttempt,
    onPause,
    onResume,
    onStop,
    onModeChange,
    onNewTask,
  } = props;
  const [confirmStop, setConfirmStop] = useState(false);
  const [goalExpanded, setGoalExpanded] = useState(false);

  const paused = run === "paused";
  const canControl = !finished && run !== "idle";
  const tone = toneFor(run, hasResult);
  const statusLabel = run === "failed" && hasResult ? "Partial result" : STATE_TEXT[run];
  const singleLineGoal = goal.replace(/\s+/g, " ").trim();

  return (
    <Collapsible.Root
      open={goalExpanded}
      onOpenChange={setGoalExpanded}
      asChild
    >
      <header className="top-bar" aria-label="Workspace header and run controls">
        <div className="top-bar-main">
          <div className="top-bar-left">
            <button
              type="button"
              className="brand-btn"
              onClick={finished ? onNewTask : undefined}
              title={finished ? "Start a new task" : "HyperAgent"}
            >
              <span className="brand-icon" aria-hidden="true">
                <Sparkles size={14} />
              </span>
              <span className="brand-name">HyperAgent</span>
            </button>

            <span className="top-divider" aria-hidden="true" />

            <div className="run-status-pill" data-tone={tone}>
              <span className={DOT_CLASS[tone]} aria-hidden="true" />
              <span className="run-status-text" role="status" aria-live="polite">
                {statusLabel}
              </span>
            </div>
            {goal ? (
              <div className="goal-pill-wrap">
                <Collapsible.Trigger asChild>
                  <button type="button" className="goal-pill goal-pill-interactive"
                    aria-label={goalExpanded ? "Hide full task" : "Show full task"}>
                    <span className="goal-pill-text">{singleLineGoal}</span>
                    {goalExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                  </button>
                </Collapsible.Trigger>
              </div>
            ) : null}
          </div>

          <div className="top-bar-right">
            <div className="telemetry-bar" aria-label="Run metrics">
              <span className="telemetry-chip" title="Steps executed">
                <Activity size={13} aria-hidden="true" />
                <strong>
                  {stepNumber}
                  <span className="telemetry-muted">/{maxSteps || "–"} steps</span>
                </strong>
              </span>
              <span className="telemetry-chip" title="Elapsed time">
                <Clock size={13} aria-hidden="true" />
                <strong>{formatDuration(usage?.elapsed_s ?? elapsedS)}</strong>
              </span>
              <span className="telemetry-chip" title="Estimated LLM cost">
                <Coins size={13} aria-hidden="true" />
                <strong>{usage ? formatCost(usage.cost_usd) : "–"}</strong>
              </span>
              <span className="telemetry-chip" title="Tokens used by this task (input + output)">
                <strong>{usage ? totalTokens(usage).toLocaleString() : "–"}</strong>
                <span className="telemetry-muted">tok</span>
              </span>

            </div>

            <div className="mode-select-wrap">
              <label className="sr-only" htmlFor="approval-mode">
                Approval mode
              </label>
              {mode === "never" ? (
                <Zap size={13} className="mode-icon" aria-hidden="true" />
              ) : mode === "always" ? (
                <ShieldAlert size={13} className="mode-icon" aria-hidden="true" />
              ) : (
                <ShieldCheck size={13} className="mode-icon" aria-hidden="true" />
              )}
              <select
                id="approval-mode"
                className="select select-compact"
                value={mode}
                onChange={(event) => onModeChange(event.target.value as ApprovalMode)}
                disabled={finished}
                title="Change how often the agent asks before acting"
              >
                <option value="risky">Ask on risky</option>
                <option value="always">Ask every step</option>
                <option value="never">Autonomous</option>
              </select>
            </div>

            <div className="control-actions">
              {finished ? (
                <button type="button" className="btn btn-primary btn-sm" onClick={onNewTask}>
                  <Plus size={14} aria-hidden="true" />
                  New task
                </button>
              ) : (
                <>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={paused ? onResume : onPause}
                    disabled={!canControl}
                    aria-keyshortcuts="Escape"
                    title={paused ? "Resume run (Esc)" : "Pause run (Esc)"}
                  >
                    {paused ? <Play size={13} aria-hidden="true" /> : <Pause size={13} aria-hidden="true" />}
                    {paused ? "Resume" : "Pause"}
                  </button>
                  {confirmStop ? (
                    <span className="confirm-stop-group" role="group" aria-label="Confirm stop">
                      <button
                        type="button"
                        className="btn btn-danger btn-sm"
                        onClick={() => {
                          setConfirmStop(false);
                          onStop();
                        }}
                      >
                        Confirm stop
                      </button>
                      <button
                        type="button"
                        className="btn btn-quiet btn-sm"
                        onClick={() => setConfirmStop(false)}
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-danger btn-sm"
                      onClick={() => setConfirmStop(true)}
                      disabled={!canControl}
                      title="Stop run"
                    >
                      <Square size={12} aria-hidden="true" />
                      Stop
                    </button>
                  )}
                </>
              )}
            </div>
            <RunDetails usage={usage} chatUsage={chatUsage} allChatsUsage={allChatsUsage}
              detail={detail} connection={connection} reconnectAttempt={reconnectAttempt} />
          </div>
        </div>

        <Collapsible.Content className="goal-drawer">
          <div className="goal-drawer-inner">
            <span className="eyebrow">Full Goal</span>
            <p className="goal-drawer-text">{goal}</p>
          </div>
        </Collapsible.Content>
      </header>
    </Collapsible.Root>
  );
}

function RunDetails({ usage, chatUsage, allChatsUsage, detail, connection, reconnectAttempt }: {
  usage: Usage | null;
  chatUsage: Usage;
  allChatsUsage: Usage;
  detail: string;
  connection: ConnectionState;
  reconnectAttempt: number;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: PointerEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      trigger.current?.focus();
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open]);
  const fastCalls = usage?.fast_calls ?? 0;
  return (
    <div className="run-details" ref={root}>
      <button ref={trigger} type="button" className="btn btn-sm" aria-label="Run details"
        title="Run details" aria-expanded={open} aria-controls="run-details-panel"
        onClick={() => setOpen((value) => !value)}>
        <MoreHorizontal size={16} aria-hidden="true" />
        {connection !== "open" ? <span className="dot dot-wait" aria-label="Connection interrupted" /> : null}
      </button>
      {open ? (
        <section id="run-details-panel" className="run-details-panel" aria-label="Run details">
          <h2>Run details</h2>
          <table className="usage-totals" aria-label="Token and cost totals">
            <thead><tr><th scope="col">Usage</th><th scope="col">Tokens</th><th scope="col">Cost</th></tr></thead>
            <tbody>
              {[["This task", usage], ["This chat", chatUsage], ["All saved chats", allChatsUsage]].map(([label, value]) => {
                const total = value as Usage | null;
                return <tr key={String(label)}><th scope="row">{String(label)}</th>
                  <td>{total ? totalTokens(total).toLocaleString() : "–"}</td>
                  <td>{total ? formatCost(total.cost_usd) : "–"}</td></tr>;
              })}
            </tbody>
          </table>
          <p>Recorded input + output tokens. All saved chats covers this browser; deleted chats and usage that was not recorded are excluded.</p>
          {detail ? <p>{detail}</p> : null}
          <dl>
            <div><dt>Connection</dt><dd>{connection === "open" ? "Connected" : connection === "reconnecting" ? `Reconnecting (attempt ${reconnectAttempt})` : "Offline"}</dd></div>
            <div><dt>Model calls</dt><dd>{usage?.llm_calls ?? "–"}</dd></div>
            <div><dt>Input tokens</dt><dd>{usage?.input_tokens.toLocaleString() ?? "–"}</dd></div>
            <div><dt>Output tokens</dt><dd>{usage?.output_tokens.toLocaleString() ?? "–"}</dd></div>
            <div><dt>Jev decisions</dt><dd>{fastCalls}</dd></div>
            <div><dt>Average Jev decision</dt><dd>{fastCalls ? `${Math.round((usage?.fast_ms_total ?? 0) / fastCalls)}ms` : "–"}</dd></div>
          </dl>
          <p>Jev decisions include actions that failed or were skipped. Token savings are not measured.</p>
        </section>
      ) : null}
    </div>
  );
}

interface GuidanceComposerProps {
  question: Question | null;
  finished: boolean;
  hasLiveBrowser?: boolean;
  /** Text to place in the box (e.g. a suggested follow-up); a new nonce re-applies the same text. */
  seed?: { text: string; nonce: number } | null;
  pinnedPoint?: { x: number; y: number } | null;
  onClearPin?: () => void;
  onGuide: (text: string, pin?: { x: number; y: number } | null) => boolean;
  onContinueOnPage?: (goal: string) => boolean;
  onStartNewTask?: (goal: string) => boolean;
}

export function GuidanceComposer({
  question,
  finished,
  hasLiveBrowser,
  seed,
  pinnedPoint,
  onClearPin,
  onGuide,
  onContinueOnPage,
  onStartNewTask,
}: GuidanceComposerProps) {
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!seed) return;
    setDraft(seed.text);
    inputRef.current?.focus();
  }, [seed]);

  if (finished && !question && !onStartNewTask && !onContinueOnPage) return null;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed) return;
    if (finished && !question) {
      if (hasLiveBrowser && onContinueOnPage) {
        const goalWithPin = pinnedPoint
          ? `[Pinned element at (${pinnedPoint.x}, ${pinnedPoint.y})] ${trimmed}`
          : trimmed;
        if (onContinueOnPage(goalWithPin)) {
          setDraft("");
          onClearPin?.();
        }
        return;
      }
      if (onStartNewTask) {
        if (onStartNewTask(trimmed)) {
          setDraft("");
          onClearPin?.();
        }
        return;
      }
    }
    if (onGuide(draft, pinnedPoint)) {
      setDraft("");
      onClearPin?.();
    }
  };

  return (
    <div className="sidebar-composer">
      {question ? (
        <div className="question-card" role="alert">
          <HelpCircle size={16} className="question-icon" aria-hidden="true" />
          <div className="question-body">
            <span className="question-label">Agent needs your input</span>
            <p>{question.question}</p>
          </div>
        </div>
      ) : null}

      {pinnedPoint ? (
        <div className="pinned-target-chip" role="status">
          <span>
            📍 Pinned target at <strong>({pinnedPoint.x}, {pinnedPoint.y})</strong> on page
          </span>
          {onClearPin ? (
            <button type="button" className="pinned-chip-clear" onClick={onClearPin} title="Remove pin">
              Clear
            </button>
          ) : null}
        </div>
      ) : null}

      <form className="guide-form" onSubmit={submit}>
        <label className="sr-only" htmlFor="guidance">
          {question ? "Your answer" : finished ? "Follow-up or new task goal" : "Message to the agent"}
        </label>
        <input
          ref={inputRef}
          id="guidance"
          className="guide-input"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={
            pinnedPoint
              ? `Tell the agent what to do with the pinned element at (${pinnedPoint.x}, ${pinnedPoint.y})…`
              : question
                ? "Type your answer and press Enter…"
                : finished
                  ? hasLiveBrowser
                    ? "Ask a follow-up on this page, or in a fresh browser…"
                    : "Ask a follow-up or a new question…"
                  : "Guide the agent or add instructions…"
          }
          autoComplete="off"
        />
        {finished && !question && hasLiveBrowser && onContinueOnPage && onStartNewTask ? (
          <div className="composer-followup-btns">
            <button
              type="submit"
              className="guide-submit"
              disabled={draft.trim().length === 0}
              title="Continue with this instruction on the currently open browser page"
            >
              <ArrowRight size={14} aria-hidden="true" />
              <span>Continue here</span>
            </button>
            <button
              type="button"
              className="btn btn-sm"
              disabled={draft.trim().length === 0}
              onClick={() => {
                const trimmed = draft.trim();
                if (trimmed && onStartNewTask(trimmed)) {
                  setDraft("");
                  onClearPin?.();
                }
              }}
              title="Open a brand-new browser and run this as a fresh task"
            >
              <Plus size={13} aria-hidden="true" />
              <span>New browser</span>
            </button>
          </div>
        ) : (
          <button
            type="submit"
            className="guide-submit"
            disabled={draft.trim().length === 0}
            title={question ? "Send answer" : finished ? "Ask in this chat (opens a fresh browser)" : "Send guidance"}
          >
            <Send size={14} aria-hidden="true" />
            <span>{question ? "Answer" : "Send"}</span>
          </button>
        )}
      </form>
    </div>
  );
}
