import {
  AlertCircle,
  ArrowUpDown,
  BookmarkCheck,
  CheckCircle2,
  ChevronRight,
  Eye,
  FileSearch,
  Globe,
  HelpCircle,
  Keyboard,
  Layers,
  MousePointerClick,
  Search,
  Sparkles,
  Zap,
} from "lucide-react";
import type { StepRecord, StepStatus } from "@/lib/protocol";
import { formatDuration } from "@/lib/format";

interface StatusInfo {
  label: string;
  tone: "live" | "ok" | "wait" | "error" | "neutral";
}

const STATUS: Record<StepStatus, StatusInfo> = {
  thinking: { label: "Thinking", tone: "live" },
  planned: { label: "Planned", tone: "neutral" },
  awaiting_approval: { label: "Needs approval", tone: "wait" },
  running: { label: "Running", tone: "live" },
  ok: { label: "Done", tone: "ok" },
  error: { label: "Failed", tone: "error" },
  rejected: { label: "Rejected", tone: "neutral" },
  skipped: { label: "Skipped", tone: "neutral" },
};

function ActionIcon({ name, isFast }: { name?: string; isFast: boolean }) {
  if (isFast) return <Zap size={13} className="step-tool-icon" aria-hidden="true" />;
  switch (name) {
    case "navigate":
      return <Globe size={13} className="step-tool-icon" aria-hidden="true" />;
    case "search":
      return <Search size={13} className="step-tool-icon" aria-hidden="true" />;
    case "click":
    case "select_option":
      return <MousePointerClick size={13} className="step-tool-icon" aria-hidden="true" />;
    case "type_text":
    case "press_key":
      return <Keyboard size={13} className="step-tool-icon" aria-hidden="true" />;
    case "scroll":
      return <ArrowUpDown size={13} className="step-tool-icon" aria-hidden="true" />;
    case "read_page":
      return <FileSearch size={13} className="step-tool-icon" aria-hidden="true" />;
    case "read_urls_parallel":
      return <Layers size={13} className="step-tool-icon" aria-hidden="true" />;
    case "record_findings":
      return <BookmarkCheck size={13} className="step-tool-icon" aria-hidden="true" />;
    case "delegate":
      return <Zap size={13} className="step-tool-icon" aria-hidden="true" />;
    case "ask_user":
      return <HelpCircle size={13} className="step-tool-icon" aria-hidden="true" />;
    case "done":
      return <CheckCircle2 size={13} className="step-tool-icon" aria-hidden="true" />;
    default:
      return <Sparkles size={13} className="step-tool-icon" aria-hidden="true" />;
  }
}

function cleanStepResult(step: StepRecord): string | null {
  const raw = step.result?.trim();
  if (!raw || step.error) return null;
  // Suppress trivial echoes that duplicate the action title.
  if (
    raw === "Clicked." ||
    raw === "Typed." ||
    raw === "Typed and pressed Enter." ||
    raw === "Waited." ||
    /^Selected\s+['"].*['"]\.$/i.test(raw) ||
    raw.startsWith("Jev reports the subgoal is done")
  ) {
    return null;
  }
  // For parent delegate steps, strip the long semicolon list that duplicates child Jev cards.
  if (step.action?.name === "delegate" && raw.startsWith("Jev took ")) {
    const [head] = raw.split(":");
    const tailMatch = raw.match(/Returned control because [^.]+\.?/);
    return tailMatch ? `${head}. ${tailMatch[0]}` : `${head}.`;
  }
  return raw;
}

interface StepCardProps {
  step: StepRecord;
  now: number;
  selected?: boolean;
  hasSnapshot?: boolean;
  onSelect?: () => void;
}

export function StepCard({ step, now, selected, hasSnapshot, onSelect }: StepCardProps) {
  const status = STATUS[step.status];
  const end = step.ended_at ?? now;
  const duration = end > step.started_at ? formatDuration(end - step.started_at) : null;
  const actionLabel = step.action?.label ?? "";
  const nextGoal = step.thought?.next_goal?.trim() || "";
  const evaluation = step.thought?.evaluation?.trim() || "";
  const memory = step.thought?.memory?.trim() || "";
  const showThinking = step.status === "thinking";
  const isFast = step.system === "fast";
  const showEvaluation =
    !isFast &&
    Boolean(evaluation) &&
    evaluation.toLowerCase() !== "ok" &&
    evaluation.toLowerCase() !== actionLabel.toLowerCase();
  const showNextGoal =
    !isFast &&
    Boolean(nextGoal) &&
    nextGoal.toLowerCase() !== actionLabel.toLowerCase() &&
    nextGoal.toLowerCase() !== evaluation.toLowerCase();
  const resultText = cleanStepResult(step);

  // Only show a colored status pill when the step is active, waiting, or failed.
  const showStatusPill = step.status !== "ok";

  return (
    <article
      className={`${isFast ? "step step-fast" : "step"}${selected ? " is-selected" : ""}${hasSnapshot ? " is-inspectable" : ""}`}
      data-status={step.status}
      aria-label={`Step ${step.n}: ${actionLabel || nextGoal || "Thinking"}`}
      onClick={(event) => {
        if (!onSelect || !hasSnapshot) return;
        const target = event.target as HTMLElement | null;
        if (target?.closest("summary, details, button, a, input")) return;
        onSelect();
      }}
    >
      <header className="step-head">
        <span className="step-num">#{step.n}</span>
        <span
          className="system-badge"
          title={
            isFast
              ? "Jev (System 1) fast action"
              : "Planner (System 2) decision"
          }
        >
          {isFast ? "Jev" : "Planner"}
        </span>

        {showStatusPill ? (
          <span className="pill" data-tone={status.tone}>
            {status.label}
            {showThinking ? (
              <span className="thinking-dots" aria-hidden="true">
                <span />
                <span />
                <span />
              </span>
            ) : null}
          </span>
        ) : null}

        {hasSnapshot && onSelect ? (
          <button
            type="button"
            className={`step-inspect-btn${selected ? " is-active" : ""}`}
            onClick={(event) => {
              event.stopPropagation();
              onSelect();
            }}
            title={selected ? "Exit step snapshot view" : "Inspect browser snapshot at this step"}
          >
            <Eye size={11} aria-hidden="true" />
            <span>{selected ? "Viewing" : "Inspect"}</span>
          </button>
        ) : null}

        {duration ? (
          <span className="step-duration" title="Step duration">
            {duration}
          </span>
        ) : null}
      </header>

      {showThinking && !step.action ? (
        <div className="step-thinking-live">
          <Sparkles size={12} className="thinking-spin" aria-hidden="true" />
          <span>
            {nextGoal
              ? `Planning: ${nextGoal}`
              : isFast
                ? "Selecting next UI action…"
                : "Thinking & planning next step…"}
          </span>
        </div>
      ) : null}

      {showEvaluation ? (
        <p className="step-reasoning" title="Model reasoning">
          {evaluation}
        </p>
      ) : null}

      {step.action ? (
        <div className="step-action-row">
          <ActionIcon name={step.action.name} isFast={isFast} />
          <div className="step-label">{actionLabel}</div>
        </div>
      ) : null}

      {showNextGoal ? <p className="step-next">{nextGoal}</p> : null}

      {isFast && step.confidence !== undefined ? (
        <details className="reasoning">
          <summary>
            <ChevronRight size={11} className="reasoning-chevron" aria-hidden="true" />
            <span>
              {Math.round(step.confidence * 100)}% confidence
              {step.latency_ms !== undefined ? ` · ${step.latency_ms}ms` : ""}
            </span>
          </summary>
          {step.alternatives && step.alternatives.length > 0 ? (
            <ul className="alternatives">
              {step.alternatives.map((alt) => (
                <li key={alt.label}>
                  <span className="alt-bar" style={{ width: `${Math.round(alt.p * 100)}%` }} />
                  <span className="alt-label">{alt.label}</span>
                  <span className="alt-p">{Math.round(alt.p * 100)}%</span>
                </li>
              ))}
            </ul>
          ) : null}
        </details>
      ) : null}

      {!isFast && memory && memory !== "m" ? (
        <details className="reasoning">
          <summary>
            <ChevronRight size={11} className="reasoning-chevron" aria-hidden="true" />
            <span>Working memory</span>
          </summary>
          <dl>
            <dt>Memory</dt>
            <dd>{memory}</dd>
          </dl>
        </details>
      ) : null}

      {step.error ? (
        <div className="step-error" role="alert">
          <AlertCircle size={13} aria-hidden="true" />
          <span>{step.error}</span>
        </div>
      ) : null}

      {resultText ? <p className="step-result">{resultText}</p> : null}
    </article>
  );
}
