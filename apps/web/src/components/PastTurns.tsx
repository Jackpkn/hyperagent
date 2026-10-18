"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, MessageSquare } from "lucide-react";
import type { ChatTurn } from "@/lib/chat-model";
import { frameKey, parseFrameKey } from "@/lib/chat-model";
import { ResultReport } from "./ResultReport";
import { StepCard } from "./StepCard";
import { InlineQuestion } from "./InlineQuestion";
import { totalTokens } from "@/lib/usage";
import { formatCost } from "@/lib/format";

interface PastTurnsProps {
  turns: ChatTurn[];
  /** Separate earlier turns from a live question below them. */
  showDivider?: boolean;
  /** Selected snapshot as "turnId::stepId" (see frameKey). */
  selectedKey: string | null;
  onSelectKey: (key: string | null) => void;
  onUseFollowUp?: (text: string) => void;
}

const ENDED_TEXT: Partial<Record<ChatTurn["run"], string>> = {
  stopped: "This turn was stopped before a report was written.",
  failed: "This turn ended with an error before a report was written.",
};

/** Earlier questions of the open chat, read-only, with their own time travel. */
export function PastTurns({ turns, showDivider = false, selectedKey, onSelectKey, onUseFollowUp }: PastTurnsProps) {
  if (turns.length === 0) return null;
  return (
    <div className="past-turns" aria-label="Earlier questions in this chat">
      {turns.map((turn) => (
        <PastTurn
          key={turn.id}
          turn={turn}
          selectedKey={selectedKey}
          onSelectKey={onSelectKey}
          onUseFollowUp={onUseFollowUp}
        />
      ))}
      {showDivider ? (
        <div className="past-turns-divider" role="separator">
          <span>Latest</span>
        </div>
      ) : null}
    </div>
  );
}

function PastTurn({
  turn,
  selectedKey,
  onSelectKey,
  onUseFollowUp,
}: Omit<PastTurnsProps, "turns" | "showDivider"> & { turn: ChatTurn }) {
  const [open, setOpen] = useState(false);
  const selected = selectedKey ? parseFrameKey(selectedKey) : null;
  const selectedStepId = selected?.turnId === turn.id ? selected.stepId : null;
  const inspect = (stepId: string | null) => onSelectKey(stepId ? frameKey(turn.id, stepId) : null);
  const now = turn.steps.reduce((latest, s) => Math.max(latest, s.ended_at ?? s.started_at), turn.startedAt);

  return (
    <section className="past-turn">
      <div className="feed-row feed-guidance">
        <div className="guidance-bubble is-goal">
          <span className="guidance-meta">
            <MessageSquare size={11} aria-hidden="true" /> You
          </span>
          {turn.goal}
        </div>
      </div>

      {turn.usage ? <p className="past-turn-usage">
        This task · {totalTokens(turn.usage).toLocaleString()} tokens · {formatCost(turn.usage.cost_usd)}
      </p> : null}

      {turn.steps.length > 0 ? (
        <button
          type="button"
          className="past-turn-toggle"
          aria-expanded={open}
          onClick={() => setOpen((prev) => !prev)}
        >
          {open ? <ChevronDown size={13} aria-hidden="true" /> : <ChevronRight size={13} aria-hidden="true" />}
          <span>
            {open ? "Hide" : "Show"} {turn.steps.length} {turn.steps.length === 1 ? "step" : "steps"}
          </span>
        </button>
      ) : null}

      {open ? (
        <div className="feed past-turn-steps">
          {turn.steps.map((step) => (
            <div key={step.id} className="feed-row" data-status={step.status}>
              <StepCard
                step={step}
                hideResult={turn.feed.some((item) => item.kind === "question" && item.stepId === step.id && item.answer)}
                now={now}
                selected={selectedStepId === step.id}
                hasSnapshot={turn.frameSteps.includes(step.id)}
                onSelect={() => inspect(selectedStepId === step.id ? null : step.id)}
              />
              {turn.feed.filter((item) => item.kind === "question" && item.stepId === step.id).map((item) =>
                item.kind === "question" ? <InlineQuestion key={item.key} question={item.question} answer={item.answer} /> : null)}
            </div>
          ))}
        </div>
      ) : null}

      {turn.result ? (
        <div className="stream-result-block">
          <ResultReport
            result={turn.result}
            usage={turn.usage}
            findings={turn.findings}
            goal={turn.goal}
            steps={turn.steps}
            selectedStepId={selectedStepId}
            onInspectStep={inspect}
            onUseFollowUp={onUseFollowUp}
          />
        </div>
      ) : (
        <div className="notice" data-level="warn" role="status">
          <span>{ENDED_TEXT[turn.run] ?? "This turn ended without a report."}</span>
        </div>
      )}
    </section>
  );
}
