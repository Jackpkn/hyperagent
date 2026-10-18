import { AlertCircle, ChevronRight, Eye } from "lucide-react";
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

function cleanStepResult(step: StepRecord): string | null {
  const raw = step.result?.trim();
  if (!raw || step.error) return null;
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
  if (step.action?.name === "delegate" && raw.startsWith("Jev took ")) {
    // "Jev took 0 actions. Returned control because …" has no action log to shorten.
    if (!raw.includes(":")) return raw;
    const [head] = raw.split(":");
    const tailMatch = raw.match(/Returned control because [^.]+\.?/);
    return tailMatch ? `${head}. ${tailMatch[0]}` : `${head}.`;
  }
  return raw;
}

function singleLinePreview(text: string, maxLen = 140): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (flat.length <= maxLen) return flat;
  return `${flat.slice(0, maxLen).trimEnd()}…`;
}

interface StepCardProps {
  step: StepRecord;
  now: number;
  selected?: boolean;
  hasSnapshot?: boolean;
  onSelect?: () => void;
  hideResult?: boolean;
}

export function StepCard({ step, now, selected, hasSnapshot, onSelect, hideResult = false }: StepCardProps) {
  const uncertain = step.status === "ok" && step.verification?.status === "unverified";
  const status: StatusInfo = uncertain ? { label: "Unverified", tone: "wait" } :
    step.status === "ok" && step.verification?.status === "verified" ? { label: "Verified", tone: "ok" } :
    STATUS[step.status];
  const end = step.ended_at ?? now;
  const duration = end > step.started_at ? formatDuration(end - step.started_at) : null;
  const actionLabel = step.action?.label ?? "";
  const nextGoal = step.thought?.next_goal?.trim() || "";
  const evaluation = step.thought?.evaluation?.trim() || "";
  const nativeThinking = step.thought?.thinking?.trim() || "";
  const memory = step.thought?.memory?.trim() || "";
  const narration = step.thought?.message?.trim() || "";
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
  const resultText = hideResult ? null : cleanStepResult(step) ?? step.verification?.detail;

  const rawThoughtSource = nativeThinking || (showEvaluation ? evaluation : "") || (showNextGoal ? nextGoal : "");
  const thoughtPreview = rawThoughtSource ? singleLinePreview(rawThoughtSource, 130) : "";
  const hasThoughtDetails = !isFast && Boolean(nativeThinking || showEvaluation || (memory && memory !== "m"));

  // Inline parenthetical detail for the action line (● Action (detail))
  const inlineDetail = resultText || (showNextGoal ? nextGoal : "");

  return (
    <article
      className={`stream-step${isFast ? " is-fast" : ""}`}
      data-status={step.status}
      aria-label={`Step ${step.n}: ${actionLabel || nextGoal || "Thinking"}`}
    >
      {/* 0. Narration: the agent's plain-language update for the person watching (streams live). */}
      {narration && !isFast ? <p className="stream-narration">{narration}</p> : null}

      {/* 1. Thought row: ○ Thought for Xs (...) */}
      {showThinking ? (
        <div className="stream-line stream-line-thought is-live">
          <span className="stream-bullet is-hollow is-pulsing" aria-hidden="true">
            ○
          </span>
          <div className="stream-thought-live-body">
            <span className="stream-thought-title">
              Thinking{duration ? ` for ${duration}` : ""}
            </span>
            <span className="stream-thought-live-text">
              {" ("}
              {nativeThinking ||
                evaluation ||
                nextGoal ||
                (isFast ? "Selecting next UI action…" : "Analyzing page & planning next step…")}
              {")"}
            </span>
          </div>
        </div>
      ) : hasThoughtDetails ? (
        <details className="stream-thought-details">
          <summary className="stream-line stream-line-thought">
            <span className="stream-bullet is-hollow" aria-hidden="true">
              ○
            </span>
            <span className="stream-thought-summary">
              <span className="stream-thought-title">
                Thought{duration ? ` for ${duration}` : ""}
              </span>
              {thoughtPreview ? (
                <span className="stream-thought-preview"> ({thoughtPreview})</span>
              ) : null}
            </span>
            <ChevronRight size={11} className="reasoning-chevron" aria-hidden="true" />
          </summary>
          <div className="stream-thought-expanded">
            {nativeThinking ? <p className="stream-thought-para">{nativeThinking}</p> : null}
            {showEvaluation && evaluation !== nativeThinking ? (
              <p className="stream-thought-para">
                <strong>Observation:</strong> {evaluation}
              </p>
            ) : null}
            {memory && memory !== "m" ? (
              <p className="stream-thought-para">
                <strong>Memory:</strong> {memory}
              </p>
            ) : null}
          </div>
        </details>
      ) : null}

      {/* 2. Action row: ● Action (result / detail) */}
      {step.action || (!showThinking && (step.error || step.result)) ? (
        <div
          className={`stream-line stream-line-action${selected ? " is-selected" : ""}${hasSnapshot ? " is-inspectable" : ""}`}
          data-tone={status.tone}
          onClick={(event) => {
            if (!onSelect || !hasSnapshot) return;
            const target = event.target as HTMLElement | null;
            if (target?.closest("summary, details, button, a, input")) return;
            onSelect();
          }}
        >
          <span className="stream-bullet is-solid" data-tone={status.tone} aria-hidden="true">
            {uncertain ? "?" : step.status === "ok" ? "✓" : step.status === "error" ? "×" :
              step.status === "skipped" || step.status === "rejected" ? "–" : "○"}
          </span>
          <div className="stream-action-main">
            <span className="sr-only">{status.label}: </span>
            {isFast ? <span className="stream-fast-tag">⚡ Fast</span> : null}
            <span className="stream-action-title">{actionLabel || status.label}</span>
            {inlineDetail ? (
              <span className="stream-action-detail"> ({inlineDetail})</span>
            ) : null}
            {isFast && step.confidence !== undefined ? (
              <span className="stream-fast-meta">
                {" · "}
                {Math.round(step.confidence * 100)}%
                {step.latency_ms !== undefined ? ` · ${step.latency_ms}ms` : ""}
              </span>
            ) : null}
          </div>

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
        </div>
      ) : null}

      {step.error ? (
        <div className="stream-error-line" role="alert">
          <AlertCircle size={12} aria-hidden="true" />
          <span>{step.error}</span>
        </div>
      ) : null}
    </article>
  );
}
