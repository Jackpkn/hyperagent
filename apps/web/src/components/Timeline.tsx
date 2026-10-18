"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import * as Collapsible from "@radix-ui/react-collapsible";
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Circle,
  Database,
  FileCheck2,
  Info,
  ListChecks,
  MessageSquare,
} from "lucide-react";
import type { Approval, Finding, Frame, PlanItem, RunResult, StepRecord, Usage } from "@/lib/protocol";
import type { FeedItem } from "@/lib/agent-state";
import { ApprovalCard } from "./ApprovalCard";
import { FindingCard } from "./ResultsPanel";
import { ResultReport } from "./ResultReport";
import { StepCard } from "./StepCard";

const NEAR_BOTTOM_PX = 100;

interface TimelineProps {
  goal?: string;
  runState?: string;
  runDetail?: string;
  plan: PlanItem[];
  steps: StepRecord[];
  feed: FeedItem[];
  approvals: Record<string, Approval>;
  findings?: Finding[];
  result?: RunResult | null;
  previousResult?: RunResult | null;
  usage?: Usage | null;
  fastModel?: string | null;
  finished?: boolean;
  endedWithoutResult?: string | null;
  stepFrames?: Record<string, Frame>;
  selectedStepId?: string | null;
  now: number;
  onSelectStep?: (stepId: string | null) => void;
  onUseFollowUp?: (text: string) => void;
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
  goal = "",
  runState = "",
  runDetail = "",
  plan,
  steps,
  feed,
  approvals,
  findings = [],
  result = null,
  previousResult = null,
  usage = null,
  fastModel = null,
  finished = false,
  endedWithoutResult = null,
  stepFrames,
  selectedStepId,
  now,
  onSelectStep,
  onUseFollowUp,
  onApprove,
  onReject,
}: TimelineProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const resultAnchorRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const [planOpen, setPlanOpen] = useState(false);
  const [findingsOpen, setFindingsOpen] = useState(true);
  const [expandAllFeed, setExpandAllFeed] = useState(false);

  const stepById = useMemo(() => new Map(steps.map((step) => [step.id, step])), [steps]);
  const doneCount = useMemo(
    () => plan.filter((item) => item.status === "done").length,
    [plan],
  );
  const activePlan = useMemo(
    () => plan.find((item) => item.status === "active") ?? plan.find((item) => item.status === "pending"),
    [plan],
  );

  // Collapse intermediate findings drawer automatically once the final report arrives so the report is front-and-center.
  useEffect(() => {
    if (result) {
      setFindingsOpen(false);
      requestAnimationFrame(() => {
        resultAnchorRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    } else {
      setFindingsOpen(true);
    }
  }, [result]);

  useEffect(() => {
    const element = scrollRef.current;
    if (element && stickToBottom.current) {
      element.scrollTop = element.scrollHeight;
    }
  }, [feed.length, steps, approvals, findings.length, result]);

  const onScroll = () => {
    const element = scrollRef.current;
    if (!element) return;
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
    if (distance < NEAR_BOTTOM_PX) stickToBottom.current = true;
  };

  const releaseStick = () => {
    stickToBottom.current = false;
  };

  const renderFeedItem = (item: FeedItem) => {
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
          <div style={{ marginTop: 8, marginLeft: 18 }}>
            <ApprovalCard
              approval={approval}
              onApprove={onApprove}
              onReject={onReject}
            />
          </div>
        ) : null}
      </div>
    );
  };

  const canRollup = feed.length > 10;
  const hiddenCount = canRollup ? feed.length - 8 : 0;

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
        {!goal && feed.length === 0 && !result && findings.length === 0 ? (
          <div className="empty-state">
            <Circle size={20} className="empty-icon" aria-hidden="true" />
            <p className="empty-title">Starting run</p>
            <p className="empty-sub">The agent&apos;s actions, thinking, findings, and final report will stream here live.</p>
          </div>
        ) : (
          <div className="stream-stack">
            {goal ? (
              <div className="feed-row feed-guidance">
                <div className="guidance-bubble is-goal">
                  <span className="guidance-meta">
                    <MessageSquare size={11} aria-hidden="true" /> You
                  </span>
                  {goal}
                </div>
              </div>
            ) : null}

            {feed.length > 0 ? (
              <div className="feed">
                {canRollup && !expandAllFeed ? (
                  <>
                    {feed.slice(0, 2).map(renderFeedItem)}
                    <button
                      type="button"
                      className="stream-rollup-btn"
                      onClick={() => setExpandAllFeed(true)}
                    >
                      … {hiddenCount} more actions (click to expand) …
                    </button>
                    {feed.slice(-6).map(renderFeedItem)}
                  </>
                ) : (
                  <>
                    {canRollup ? (
                      <button
                        type="button"
                        className="stream-rollup-btn"
                        onClick={() => setExpandAllFeed(false)}
                      >
                        Collapse {hiddenCount} middle actions
                      </button>
                    ) : null}
                    {feed.map(renderFeedItem)}
                  </>
                )}
              </div>
            ) : null}

            {!finished &&
            !steps.some((s) => s.status === "thinking" || s.status === "running" || s.status === "awaiting_approval") ? (
              <div className="stream-live-loader" role="status" aria-live="polite">
                <span className="stream-bullet is-hollow is-pulsing" aria-hidden="true">
                  ○
                </span>
                <span className="stream-loader-text">
                  {runState === "paused"
                    ? "Paused — take over in the browser, send guidance below, or press Resume."
                    : runDetail || (steps.length === 0 ? "Launching browser & opening initial page…" : "Observing page & preparing next step…")}
                </span>
                {runState !== "paused" ? (
                  <span className="thinking-dots" aria-hidden="true">
                    <span />
                    <span />
                    <span />
                  </span>
                ) : null}
              </div>
            ) : null}

            {findings.length > 0 ? (
              <Collapsible.Root
                open={findingsOpen}
                onOpenChange={setFindingsOpen}
                className="stream-section-card"
              >
                <Collapsible.Trigger asChild>
                  <button type="button" className="stream-section-trigger">
                    <span className="stream-section-title">
                      <Database size={13} aria-hidden="true" />
                      <span>Collected Findings ({findings.length})</span>
                      <span className="verify-badge is-verified">
                        {findings.some((f) => (f.unverified?.length ?? 0) > 0)
                          ? "⚠ Check flags"
                          : "✓ Grounded"}
                      </span>
                    </span>
                    {findingsOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </button>
                </Collapsible.Trigger>
                <Collapsible.Content className="stream-section-body">
                  <ul className="findings-list" aria-label="Collected data">
                    {findings.map((finding, index) => (
                      <li key={`${index}-${finding.source_url}`}>
                        <FindingCard
                          finding={finding}
                          index={index + 1}
                          selectedStepId={selectedStepId}
                          onInspectStep={onSelectStep}
                        />
                      </li>
                    ))}
                  </ul>
                </Collapsible.Content>
              </Collapsible.Root>
            ) : null}

            {result ? (
              <section
                ref={resultAnchorRef}
                className="stream-result-block"
                aria-label="Final result in stream"
              >
                <div className="stream-result-header">
                  <FileCheck2 size={14} aria-hidden="true" />
                  <span>Final Deliverable</span>
                </div>
                <ResultReport
                  result={result}
                  previousResult={previousResult}
                  usage={usage}
                  fastModel={fastModel}
                  findings={findings}
                  goal={goal}
                  steps={steps}
                  selectedStepId={selectedStepId}
                  onInspectStep={onSelectStep}
                  onUseFollowUp={onUseFollowUp}
                />
              </section>
            ) : finished && endedWithoutResult ? (
              <div className="notice" data-level="warn" role="status">
                <AlertTriangle size={14} className="notice-icon" aria-hidden="true" />
                <span>{endedWithoutResult}</span>
              </div>
            ) : null}
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
