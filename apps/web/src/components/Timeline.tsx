"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import * as Collapsible from "@radix-ui/react-collapsible";
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Circle,
  Info,
  ListChecks,
  MessageSquare,
} from "lucide-react";
import type { Approval, Frame, PlanItem, StepRecord } from "@/lib/protocol";
import type { FeedItem } from "@/lib/agent-state";
import { ApprovalCard } from "./ApprovalCard";
import { StepCard } from "./StepCard";

const NEAR_BOTTOM_PX = 80;

interface TimelineProps {
  plan: PlanItem[];
  steps: StepRecord[];
  feed: FeedItem[];
  approvals: Record<string, Approval>;
  stepFrames?: Record<string, Frame>;
  selectedStepId?: string | null;
  now: number;
  onSelectStep?: (stepId: string | null) => void;
  onApprove: (stepId: string) => void;
  onReject: (stepId: string, reason: string) => void;
}

const PLAN_MARK: Record<PlanItem["status"], string> = {
  pending: "",
  active: "",
  done: "✓",
  skipped: "–",
};

export function Timeline({
  plan,
  steps,
  feed,
  approvals,
  stepFrames,
  selectedStepId,
  now,
  onSelectStep,
  onApprove,
  onReject,
}: TimelineProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const [planOpen, setPlanOpen] = useState(false);

  const stepById = useMemo(() => new Map(steps.map((step) => [step.id, step])), [steps]);
  const doneCount = useMemo(
    () => plan.filter((item) => item.status === "done").length,
    [plan],
  );
  const activePlan = useMemo(
    () => plan.find((item) => item.status === "active") ?? plan.find((item) => item.status === "pending"),
    [plan],
  );

  useEffect(() => {
    const element = scrollRef.current;
    if (element && stickToBottom.current) {
      element.scrollTop = element.scrollHeight;
    }
  }, [feed.length, steps, approvals]);

  const onScroll = () => {
    const element = scrollRef.current;
    if (!element) return;
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
    if (distance < NEAR_BOTTOM_PX) stickToBottom.current = true;
  };

  const releaseStick = () => {
    stickToBottom.current = false;
  };

  return (
    <div className="timeline-pane">
      {plan.length > 0 ? (
        <Collapsible.Root open={planOpen} onOpenChange={setPlanOpen} className="plan-drawer">
          <Collapsible.Trigger asChild>
            <button type="button" className="plan-summary-bar">
              <div className="plan-summary-left">
                <ListChecks size={14} className="plan-icon" aria-hidden="true" />
                <span className="plan-count">
                  Plan · {doneCount}/{plan.length}
                </span>
                {activePlan ? (
                  <span className="plan-active-text" title={activePlan.text}>
                    {activePlan.text}
                  </span>
                ) : null}
              </div>
              {planOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          </Collapsible.Trigger>
          <Collapsible.Content className="plan-drawer-content">
            <ul className="plan" aria-label="Agent plan">
              {plan.map((item, index) => (
                <li key={`${index}-${item.text}`} data-status={item.status}>
                  <span className="plan-mark" data-status={item.status} aria-hidden="true">
                    {PLAN_MARK[item.status]}
                  </span>
                  <span>
                    {item.text}
                    <span className="sr-only"> ({planWord(item.status)})</span>
                  </span>
                </li>
              ))}
            </ul>
          </Collapsible.Content>
        </Collapsible.Root>
      ) : null}

      <div
        className="panel-body timeline-scroll"
        ref={scrollRef}
        onScroll={onScroll}
        onWheel={(event) => {
          if (event.deltaY < 0) releaseStick();
        }}
        onTouchStart={releaseStick}
      >
        {feed.length === 0 ? (
          <div className="empty-state">
            <Circle size={20} className="empty-icon" aria-hidden="true" />
            <p className="empty-title">Starting run</p>
            <p className="empty-sub">The agent&apos;s actions and reasoning will stream here live.</p>
          </div>
        ) : (
          <div className="feed">
            {feed.map((item) => {
              if (item.kind === "notice") {
                return (
                  <div key={item.key} className="feed-row feed-notice">
                    <div
                      className="notice"
                      data-level={item.level}
                      role={item.level === "error" ? "alert" : "status"}
                    >
                      {item.level === "error" || item.level === "warn" ? (
                        <AlertTriangle size={14} className="notice-icon" aria-hidden="true" />
                      ) : (
                        <Info size={14} className="notice-icon" aria-hidden="true" />
                      )}
                      <span>{item.message}</span>
                    </div>
                  </div>
                );
              }
              if (item.kind === "guidance") {
                return (
                  <div key={item.key} className="feed-row feed-guidance">
                    <div className="guidance-bubble">
                      <span className="guidance-meta">
                        <MessageSquare size={11} aria-hidden="true" /> You
                      </span>
                      {item.text}
                    </div>
                  </div>
                );
              }
              const step = stepById.get(item.stepId);
              if (!step) return null;
              const approval = approvals[step.id];
              const hasSnapshot = Boolean(stepFrames?.[step.id]);
              const selected = selectedStepId === step.id;
              return (
                <div key={item.key} className="feed-row" data-status={step.status}>
                  <span className="spine-dot" aria-hidden="true" />
                  <StepCard
                    step={step}
                    now={now}
                    selected={selected}
                    hasSnapshot={hasSnapshot}
                    onSelect={
                      onSelectStep
                        ? () => onSelectStep(selected ? null : step.id)
                        : undefined
                    }
                  />
                  {approval ? (
                    <div style={{ marginTop: 10 }}>
                      <ApprovalCard
                        approval={approval}
                        onApprove={onApprove}
                        onReject={onReject}
                      />
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function planWord(status: PlanItem["status"]): string {
  switch (status) {
    case "done":
      return "done";
    case "active":
      return "in progress";
    case "skipped":
      return "skipped";
    case "pending":
      return "not started";
  }
}
