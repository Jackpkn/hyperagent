"use client";

import { useEffect, useRef, useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import {
  Database,
  FileCheck2,
  ListTodo,
  Maximize2,
  Minimize2,
  RefreshCw,
  Sparkles,
  WifiOff,
} from "lucide-react";
import { useAgent } from "@/lib/use-agent";
import { currentStep, isRunFinished } from "@/lib/agent-state";
import type { AgentState } from "@/lib/agent-state";
import type { RunState } from "@/lib/protocol";
import { useNow } from "@/lib/use-now";
import {
  clearRunHistory,
   defaultOperatorProfile,
  deleteRunHistoryItem,
  formatOperatorContext,
  hasOperatorProfileData,
  loadOperatorProfile,
  loadPersistSession,
  loadRunHistory,
  saveOperatorProfile,
  savePersistSession,
  upsertRunHistory,
  type OperatorProfile,
  type RunHistoryEntry,
} from "@/lib/operator-store";
import { BrowserView, type BrowserTarget } from "./BrowserView";
import { ControlBar, GuidanceComposer } from "./ControlBar";
import { Launcher } from "./Launcher";
import { HistoryModal, ProfileModal } from "./OperatorModals";
import { ResultsPanel } from "./ResultsPanel";
import { Timeline } from "./Timeline";

const CONNECTION_TEXT: Record<AgentState["connection"], string> = {
  connecting: "Connecting…",
  open: "Connected",
  reconnecting: "Reconnecting…",
  closed: "Offline",
};

const RUN_TEXT: Record<RunState, string> = {
  idle: "Ready",
  starting: "Starting browser",
  running: "Working",
  thinking: "Thinking…",
  acting: "Acting on page",
  paused: "Paused · Click or scroll on the page to take over",
  awaiting_approval: "Waiting for your approval",
  awaiting_user: "Waiting for your answer · Or interact with the page directly",
  finishing: "Writing final report…",
  done: "Finished",
  failed: "Stopped with an error",
  stopped: "Stopped",
};

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

type WorkspaceTab = "steps" | "findings" | "result";

export function AgentApp() {
  const agent = useAgent();
  const { state, send } = agent;
  const connected = state.connection === "open";
  const finished = isRunFinished(state.run);
  const showRun = state.active || state.run !== "idle";
  const now = useNow(showRun && !finished);

  const [activeTab, setActiveTab] = useState<WorkspaceTab>("steps");
  const [resultExpanded, setResultExpanded] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState<number>(540);
  const [isResizing, setIsResizing] = useState(false);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [pinMode, setPinMode] = useState(false);
  const [pinnedPoint, setPinnedPoint] = useState<{ x: number; y: number } | null>(null);
  const [profile, setProfile] = useState<OperatorProfile>(defaultOperatorProfile);
  const [history, setHistory] = useState<RunHistoryEntry[]>([]);
  const [persistSession, setPersistSession] = useState(false);
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [showHistoryModal, setShowHistoryModal] = useState(false);

  const lastApprovalStepRef = useRef<string | null>(null);
  const savedRunAtRef = useRef<number | null>(null);

  useEffect(() => {
    setProfile(loadOperatorProfile());
    setHistory(loadRunHistory());
    setPersistSession(loadPersistSession());
    try {
      const savedWidth = Number(window.localStorage.getItem("hyperagent.sidebarWidth.v1"));
      if (Number.isFinite(savedWidth) && savedWidth >= 380 && savedWidth <= 1100) {
        setSidebarWidth(savedWidth);
      }
    } catch {
      // Ignore storage access errors
    }
  }, []);

  const startResize = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    setResultExpanded(false);
    setIsResizing(true);
    const onMove = (moveEvent: PointerEvent) => {
      const maxW = Math.max(460, Math.round(window.innerWidth * 0.72));
      const next = Math.min(maxW, Math.max(380, Math.round(moveEvent.clientX)));
      setSidebarWidth(next);
      try {
        window.localStorage.setItem("hyperagent.sidebarWidth.v1", String(next));
      } catch {
        // Ignore storage errors
      }
    };
    const onUp = () => {
      setIsResizing(false);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const resetSidebarWidth = () => {
    setResultExpanded(false);
    setSidebarWidth(540);
    try {
      window.localStorage.setItem("hyperagent.sidebarWidth.v1", "540");
    } catch {
      // Ignore
    }
  };

  const current = currentStep(state.steps);
  const currentApproval = current ? state.approvals[current.id] : undefined;
  const approvalCount = Object.keys(state.approvals).length;
  const question = Object.values(state.questions)[0] ?? null;
  const elapsedS = state.runStartedAt ? Math.max(0, now - state.runStartedAt) : 0;
  const endedWithoutResult = finished && !state.result ? endedMessage(state) : null;

  // Keep the operator in the unified Live Stream by default; reset state when starting a new run.
  useEffect(() => {
    if (!showRun) {
      setActiveTab("steps");
      setResultExpanded(false);
      setSelectedStepId(null);
      setPinMode(false);
      setPinnedPoint(null);
      lastApprovalStepRef.current = null;
    }
  }, [showRun]);

  // Persist completed runs to local history automatically.
  useEffect(() => {
    if (!finished || !state.goal || !state.runStartedAt) return;
    if (savedRunAtRef.current === state.runStartedAt && !state.result) return;
    savedRunAtRef.current = state.runStartedAt;
    const entry: RunHistoryEntry = {
      id: `run-${Math.round(state.runStartedAt * 1000)}`,
      goal: state.goal,
      createdAt: Math.round(state.runStartedAt * 1000),
      status: state.run,
      stepsCount: state.stepNumber || state.steps.length,
      elapsedS: state.usage?.elapsed_s ?? elapsedS,
      costUsd: state.usage?.cost_usd ?? 0,
      findings: state.findings,
      result: state.result,
    };
    setHistory(upsertRunHistory(entry));
  }, [finished, state.goal, state.runStartedAt, state.run, state.stepNumber, state.steps.length, state.usage, elapsedS, state.findings, state.result]);

  // If a new approval arrives while the operator is on another tab, bring them to Live Stream.
  useEffect(() => {
    if (currentApproval && currentApproval.step_id !== lastApprovalStepRef.current) {
      lastApprovalStepRef.current = currentApproval.step_id;
      setActiveTab("steps");
      setSelectedStepId(null);
    }
  }, [currentApproval]);

  // Escape pauses or resumes a live run, unless the operator is typing.
  useEffect(() => {
    if (!showRun || finished) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || isTypingTarget(event.target)) return;
      if (state.run === "paused") send({ type: "resume" });
      else send({ type: "pause" });
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [send, showRun, finished, state.run]);

  const operatorContext = formatOperatorContext(profile);
  const hasProfile = profile.enabled && hasOperatorProfileData(profile);

  const togglePersistSession = () => {
    setPersistSession((prev) => {
      const next = !prev;
      savePersistSession(next);
      return next;
    });
  };

  // Visual Time-Travel Scrubber: if a step with a snapshot is selected, show its frame and target.
  const selectedStep = selectedStepId
    ? state.steps.find((s) => s.id === selectedStepId) ?? null
    : null;
  const selectedStepFrame = selectedStep ? state.stepFrames[selectedStep.id] ?? null : null;

  // Find the best step to highlight on the live browser:
  // 1) Any unsettled step (planned, awaiting_approval, running) with a target rect (newest first, so Jev child steps win over parent delegate).
  // 2) Otherwise, the most recent settled step on the current page URL with a target rect so the operator can see what was just clicked/typed while the next step thinks.
  const activeTargetStep = [...state.steps]
    .reverse()
    .find(
      (s) =>
        !["ok", "error", "rejected", "skipped"].includes(s.status) &&
        Boolean(s.target?.rect),
    );
  const recentTargetStep =
    !activeTargetStep && !finished
      ? [...state.steps]
          .reverse()
          .find(
            (s) =>
              s.status === "ok" &&
              Boolean(s.target?.rect) &&
              (!state.frame?.url || !s.url || s.url === state.frame.url),
          )
      : undefined;
  const highlightedStep =
    selectedStep && selectedStepFrame
      ? selectedStep
      : activeTargetStep ?? recentTargetStep ?? current;

  const target: BrowserTarget | null =
    highlightedStep && (highlightedStep.target || highlightedStep.action)
      ? {
          label: highlightedStep.target?.label ?? "",
          rect: highlightedStep.target?.rect,
          action: highlightedStep.action?.label ?? highlightedStep.target?.label ?? "",
          risky: Boolean(currentApproval || state.approvals[highlightedStep.id]),
          recent: !selectedStep && !activeTargetStep && Boolean(recentTargetStep),
        }
      : null;

  const currentRunId = state.runStartedAt ? `run-${Math.round(state.runStartedAt * 1000)}` : "";
  const previousResult =
    history.find(
      (h) => h.id !== currentRunId && h.result && h.result.rows && h.result.rows.length > 0,
    )?.result ?? null;

  const statusText = (() => {
    if (state.run === "awaiting_approval" || currentApproval)
      return "Waiting for your approval before this step";
    if (state.run === "paused") return RUN_TEXT.paused;
    if (current?.status === "running" && current.action) return `${current.action.label}…`;
    if (state.run === "failed" && state.result) return "Finished with partial result";
    return RUN_TEXT[state.run];
  })();

  return (
    <div className={showRun ? "app app-run-mode" : "app"}>
      {!showRun ? (
        <header className="app-header">
          <div className="wordmark">
            <span className="brand-icon" aria-hidden="true">
              <Sparkles size={14} />
            </span>
            HyperAgent <small>Browser operator</small>
          </div>
          <div className="conn" role="status" aria-live="polite">
            <span
              className={`dot ${connected ? "dot-open" : state.connection === "reconnecting" ? "dot-wait" : ""}`}
              aria-hidden="true"
            />
            {CONNECTION_TEXT[state.connection]}
            {state.connection === "reconnecting" && state.reconnectAttempt > 0
              ? ` (attempt ${state.reconnectAttempt})`
              : ""}
          </div>
        </header>
      ) : null}

      {state.connection === "reconnecting" || state.connection === "closed" ? (
        <div className="conn-banner" role="alert">
          <WifiOff size={15} aria-hidden="true" />
          <span>
            Lost connection to the agent server. Any active run was stopped; reconnecting
            automatically.
          </span>
          <button type="button" className="btn btn-sm" onClick={agent.reconnectNow}>
            <RefreshCw size={13} aria-hidden="true" />
            Retry now
          </button>
        </div>
      ) : null}

      {showRun ? (
        <main className="run-shell">
          <ControlBar
            goal={state.goal}
            run={state.run}
            hasResult={Boolean(state.result)}
            detail={state.detail}
            stepNumber={state.stepNumber}
            maxSteps={state.session?.max_steps ?? 0}
            elapsedS={elapsedS}
            usage={state.usage}
            mode={state.mode}
            finished={finished}
            connection={state.connection}
            reconnectAttempt={state.reconnectAttempt}
            hasProfileData={hasProfile}
            historyCount={history.length}
            onPause={() => agent.send({ type: "pause" })}
            onResume={() => agent.send({ type: "resume" })}
            onStop={() => agent.send({ type: "stop" })}
            onModeChange={(mode) => agent.changeMode(mode)}
            onNewTask={agent.reset}
            onOpenProfile={() => setShowProfileModal(true)}
            onOpenHistory={() => setShowHistoryModal(true)}
          />

          <div
            className={`run-workspace${resultExpanded ? " is-result-expanded" : ""}${isResizing ? " is-resizing" : ""}`}
            style={
              !resultExpanded
                ? ({ "--sidebar-w": `${sidebarWidth}px` } as React.CSSProperties)
                : undefined
            }
          >
            <Tabs.Root
              value={activeTab}
              onValueChange={(val) => setActiveTab(val as WorkspaceTab)}
              className="run-sidebar"
            >
              <div className="sidebar-tabs-bar">
                <Tabs.List className="sidebar-tabs-list" aria-label="Agent workspace views">
                  <Tabs.Trigger value="steps" className="sidebar-tab" title="Unified live stream: plan, steps, findings, and final report">
                    <ListTodo size={14} aria-hidden="true" />
                    <span>Live Stream</span>
                    <span
                      className={`tab-badge${approvalCount > 0 ? " is-wait" : state.result ? " is-ok" : ""}`}
                    >
                      {state.steps.length}
                    </span>
                  </Tabs.Trigger>

                  <Tabs.Trigger value="findings" className="sidebar-tab" title="Focus only on collected findings">
                    <Database size={14} aria-hidden="true" />
                    <span>Findings</span>
                    {state.findings.length > 0 ? (
                      <span className="tab-badge">{state.findings.length}</span>
                    ) : null}
                  </Tabs.Trigger>

                  <Tabs.Trigger value="result" className="sidebar-tab" title="Focus only on the final report">
                    <FileCheck2 size={14} aria-hidden="true" />
                    <span>Report Only</span>
                    {state.result ? (
                      <span
                        className={`tab-badge ${state.result.success ? "is-ok" : "is-wait"}`}
                      >
                        {state.result.success ? "Done" : "Partial"}
                      </span>
                    ) : null}
                  </Tabs.Trigger>
                </Tabs.List>

                <button
                  type="button"
                  className="tab-expand-btn"
                  onClick={() => setResultExpanded((prev) => !prev)}
                  title={resultExpanded ? "Restore split size" : "Widen left stream panel"}
                  aria-label={resultExpanded ? "Restore split size" : "Widen left stream panel"}
                >
                  {resultExpanded ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
                </button>
              </div>

              <Tabs.Content value="steps" className="sidebar-tab-content">
                <Timeline
                  plan={state.plan}
                  steps={state.steps}
                  feed={state.feed}
                  approvals={state.approvals}
                  findings={state.findings}
                  result={state.result}
                  previousResult={previousResult}
                  usage={state.usage}
                  finished={finished}
                  endedWithoutResult={endedWithoutResult}
                  stepFrames={state.stepFrames}
                  selectedStepId={selectedStepId}
                  now={now}
                  onSelectStep={setSelectedStepId}
                  onApprove={(stepId) => agent.send({ type: "approve", step_id: stepId })}
                  onReject={(stepId, reason) =>
                    agent.send({ type: "reject", step_id: stepId, reason: reason || undefined })
                  }
                />
              </Tabs.Content>

              <Tabs.Content value="findings" className="sidebar-tab-content">
                <ResultsPanel
                  mode="findings"
                  findings={state.findings}
                  result={state.result}
                  finished={finished}
                  endedWithoutResult={endedWithoutResult}
                />
              </Tabs.Content>

              <Tabs.Content value="result" className="sidebar-tab-content">
                <ResultsPanel
                  mode="result"
                  findings={state.findings}
                  result={state.result}
                  previousResult={previousResult}
                  usage={state.usage}
                  finished={finished}
                  endedWithoutResult={endedWithoutResult}
                />
              </Tabs.Content>

              <GuidanceComposer
                question={question}
                finished={finished}
                hasLiveBrowser={Boolean(state.frame)}
                pinnedPoint={pinnedPoint}
                onClearPin={() => {
                  setPinnedPoint(null);
                  setPinMode(false);
                }}
                onGuide={agent.guide}
                onContinueOnPage={(followUpGoal) => {
                  setActiveTab("steps");
                  setSelectedStepId(null);
                  return agent.startRun({
                    goal: followUpGoal,
                    startUrl: "",
                    mode: state.mode,
                    model: state.session?.model ?? "",
                    continueSession: true,
                    persistSession,
                    operatorContext,
                  });
                }}
                onStartNewTask={(newGoal) => {
                  setActiveTab("steps");
                  setSelectedStepId(null);
                  return agent.startRun({
                    goal: newGoal,
                    startUrl: "",
                    mode: state.mode,
                    model: state.session?.model ?? "",
                    continueSession: false,
                    persistSession,
                    operatorContext,
                  });
                }}
              />
            </Tabs.Root>

            <div
              className={`run-resizer${isResizing ? " is-active" : ""}`}
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize left stream panel"
              title="Drag to resize left panel · Double-click to reset width"
              onPointerDown={startResize}
              onDoubleClick={resetSidebarWidth}
            />

            <div className="run-stage">
              <BrowserView
                frame={selectedStepFrame ?? state.frame}
                target={target}
                statusText={statusText}
                paused={state.run === "paused"}
                takeoverEnabled={
                  state.run === "paused" ||
                  state.run === "awaiting_user" ||
                  (finished && Boolean(state.frame))
                }
                subtitle={browserSubtitle(state.run)}
                hasSavedSession={state.session?.has_saved_session}
                timeTravelStep={
                  selectedStep && selectedStepFrame
                    ? {
                        n: selectedStep.n,
                        label:
                          selectedStep.action?.label ??
                          selectedStep.thought?.next_goal ??
                          "",
                      }
                    : null
                }
                onExitTimeTravel={() => setSelectedStepId(null)}
                pinMode={pinMode}
                pinnedPoint={pinnedPoint}
                onTogglePinMode={() => {
                  if (pinnedPoint) {
                    setPinnedPoint(null);
                    setPinMode(false);
                  } else {
                    setPinMode((prev) => !prev);
                  }
                }}
                onPinPoint={(pt) => {
                  setPinnedPoint(pt);
                  setPinMode(false);
                }}
                onClick={(x, y) => agent.send({ type: "takeover_click", x, y })}
                onType={(text, pressEnter) =>
                  agent.send({ type: "takeover_type", text, press_enter: pressEnter })
                }
                onScroll={(dy) => agent.send({ type: "takeover_scroll", dy })}
                onSwitchTab={(tabIndex) => agent.send({ type: "takeover_tab", tab_index: tabIndex })}
                onSaveSession={() => agent.send({ type: "save_session" })}
              />
            </div>
          </div>
        </main>
      ) : (
        <main className="launch-main">
          <Launcher
            connected={connected}
            models={state.session?.models ?? []}
            defaultModel={state.session?.model ?? ""}
            fastModel={state.session?.fast_model}
            persistSession={persistSession}
            hasSavedSession={state.session?.has_saved_session}
            hasProfileData={hasProfile}
            historyCount={history.length}
            onTogglePersistSession={togglePersistSession}
            onClearSavedSession={() => agent.send({ type: "clear_session" })}
            onOpenProfile={() => setShowProfileModal(true)}
            onOpenHistory={() => setShowHistoryModal(true)}
            onStart={(opts) =>
              agent.startRun({
                ...opts,
                persistSession,
                operatorContext,
              })
            }
          />
        </main>
      )}

      {showProfileModal ? (
        <ProfileModal
          profile={profile}
          onSave={(next) => {
            setProfile(next);
            saveOperatorProfile(next);
          }}
          onClose={() => setShowProfileModal(false)}
        />
      ) : null}

      {showHistoryModal ? (
        <HistoryModal
          entries={history}
          onView={(entry) => {
            agent.loadHistoryEntry(entry);
            setActiveTab("result");
          }}
          onRerun={(rerunGoal) =>
            agent.startRun({
              goal: rerunGoal,
              startUrl: "",
              mode: state.mode,
              model: state.session?.model ?? "",
              persistSession,
              operatorContext,
            })
          }
          onDelete={(id) => setHistory(deleteRunHistoryItem(id))}
          onClearAll={() => setHistory(clearRunHistory())}
          onClose={() => setShowHistoryModal(false)}
        />
      ) : null}
    </div>
  );
}

function browserSubtitle(run: RunState): string {
  if (run === "paused") return "Paused: you can take over";
  if (isRunFinished(run)) return "Session ended";
  return "Watching live";
}

function endedMessage(state: AgentState): string {
  const lastError = [...state.steps].reverse().find((step) => step.error)?.error;
  if (state.run === "stopped") return "The run was stopped before a report was written.";
  return lastError
    ? `The run ended before a report was written. Last error: ${lastError}`
    : "The run ended before a report was written.";
}
