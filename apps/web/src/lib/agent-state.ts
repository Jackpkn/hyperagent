import type {
  Approval,
  ApprovalMode,
  Finding,
  Frame,
  Hello,
  NoticeLevel,
  PlanItem,
  Question,
  RunResult,
  RunState,
  ServerMessage,
  StepRecord,
  Usage,
} from "./protocol";

export type ConnectionState = "connecting" | "open" | "reconnecting" | "closed";

export type FeedItem =
  | { kind: "step"; key: string; stepId: string }
  | { kind: "notice"; key: string; level: NoticeLevel; message: string }
  | { kind: "guidance"; key: string; text: string };

export interface AgentState {
  connection: ConnectionState;
  reconnectAttempt: number;
  session: Hello | null;
  // True once the operator has started a run in this view. Cleared by reset.
  active: boolean;
  goal: string;
  startUrl: string;
  mode: ApprovalMode;
  runStartedAt: number | null;
  run: RunState;
  stepNumber: number;
  detail: string;
  plan: PlanItem[];
  steps: StepRecord[];
  feed: FeedItem[];
  approvals: Record<string, Approval>;
  questions: Record<string, Question>;
  frame: Frame | null;
  stepFrames: Record<string, Frame>;
  findings: Finding[];
  usage: Usage | null;
  result: RunResult | null;
  // Monotonic counter used to build stable feed keys.
  seq: number;
}

export const initialAgentState: AgentState = {
  connection: "connecting",
  reconnectAttempt: 0,
  session: null,
  active: false,
  goal: "",
  startUrl: "",
  mode: "risky",
  runStartedAt: null,
  run: "idle",
  stepNumber: 0,
  detail: "",
  plan: [],
  steps: [],
  feed: [],
  approvals: {},
  questions: {},
  frame: null,
  stepFrames: {},
  findings: [],
  usage: null,
  result: null,
  seq: 0,
};

export type AgentAction =
  | { type: "connection"; connection: ConnectionState; attempt?: number }
  | { type: "server"; message: ServerMessage }
  | {
      type: "run_started";
      goal: string;
      startUrl: string;
      mode: ApprovalMode;
      at: number;
      continueSession?: boolean;
    }
  | {
      type: "load_history";
      goal: string;
      status: RunState;
      stepsCount: number;
      elapsedS: number;
      costUsd: number;
      findings: Finding[];
      result: RunResult | null;
    }
  | { type: "guidance_sent"; text: string }
  | { type: "local_notice"; level: NoticeLevel; message: string }
  | { type: "mode_changed"; mode: ApprovalMode }
  | { type: "reset" };

function nextKey(state: AgentState, prefix: string): [string, number] {
  const seq = state.seq + 1;
  return [`${prefix}-${seq}`, seq];
}

function upsertStep(steps: StepRecord[], step: StepRecord): StepRecord[] {
  const index = steps.findIndex((existing) => existing.id === step.id);
  if (index === -1) return [...steps, step];
  return steps.map((existing, i) => (i === index ? step : existing));
}

// Removes a key from a record without mutating the original.
function omitKey<T>(record: Record<string, T>, key: string): Record<string, T> {
  if (!(key in record)) return record;
  const copy = { ...record };
  delete copy[key];
  return copy;
}

function appendFeed(state: AgentState, item: (key: string) => FeedItem): AgentState {
  const [key, seq] = nextKey(state, "f");
  return { ...state, seq, feed: [...state.feed, item(key)] };
}

function handleStep(state: AgentState, step: StepRecord): AgentState {
  const known = state.steps.some((existing) => existing.id === step.id);
  const steps = upsertStep(state.steps, step);
  // A step update resolves any approval or question tied to it.
  const approvals = omitKey(state.approvals, step.id);
  const questions = omitKey(state.questions, step.id);
  // Capture the frame when the step is planned/running (with target rect) or when first seen.
  const shouldCaptureFrame =
    state.frame &&
    (!state.stepFrames[step.id] ||
      step.status === "planned" ||
      step.status === "awaiting_approval" ||
      step.status === "running");
  const stepFrames = shouldCaptureFrame && state.frame
    ? { ...state.stepFrames, [step.id]: state.frame }
    : state.stepFrames;
  const next: AgentState = { ...state, steps, approvals, questions, stepFrames };
  if (known) return next;
  return appendFeed(next, (key) => ({ kind: "step", key, stepId: step.id }));
}

function handleStatus(
  state: AgentState,
  message: { state: RunState; step: number; detail?: string },
): AgentState {
  return {
    ...state,
    run: message.state,
    stepNumber: message.step,
    detail: message.detail ?? "",
  };
}

function handleServer(state: AgentState, message: ServerMessage): AgentState {
  switch (message.type) {
    case "hello":
      return {
        ...state,
        session: {
          session_id: message.session_id,
          model: message.model,
          models: message.models,
          max_steps: message.max_steps,
          fast_model: message.fast_model ?? null,
          has_saved_session: Boolean(message.has_saved_session),
        },
      };
    case "status":
      return handleStatus(state, message);
    case "frame": {
      const nextFrame: Frame = {
        image: message.image,
        url: message.url,
        title: message.title,
        w: message.w,
        h: message.h,
        tabs: message.tabs,
      };
      const open = currentStep(state.steps);
      const stepFrames =
        open && !state.stepFrames[open.id]
          ? { ...state.stepFrames, [open.id]: nextFrame }
          : state.stepFrames;
      return {
        ...state,
        frame: nextFrame,
        stepFrames,
      };
    }
    case "step":
      return handleStep(state, message);
    case "plan":
      return { ...state, plan: message.items };
    case "findings":
      return { ...state, findings: message.items };
    case "approval":
      return {
        ...state,
        approvals: {
          ...state.approvals,
          [message.step_id]: {
            step_id: message.step_id,
            reason: message.reason,
            action_label: message.action_label,
            target_label: message.target_label,
            args: message.args,
          },
        },
      };
    case "question":
      return {
        ...state,
        questions: {
          ...state.questions,
          [message.step_id]: { step_id: message.step_id, question: message.question },
        },
      };
    case "notice": {
      const prev = state.feed[state.feed.length - 1];
      const base = message.message.replace(/\.$/, "");
      if (
        prev &&
        prev.kind === "notice" &&
        prev.level === message.level &&
        (prev.message === message.message || prev.message.startsWith(`${base} (×`))
      ) {
        const match = prev.message.match(/\(×(\d+)\)\.?$/);
        const count = match ? Number(match[1]) + 1 : 2;
        const updated: FeedItem = {
          ...prev,
          message: `${base} (×${count}).`,
        };
        return {
          ...state,
          feed: [...state.feed.slice(0, -1), updated],
        };
      }
      return appendFeed(state, (key) => ({
        kind: "notice",
        key,
        level: message.level,
        message: message.message,
      }));
    }
    case "usage":
      return {
        ...state,
        usage: {
          llm_calls: message.llm_calls,
          input_tokens: message.input_tokens,
          output_tokens: message.output_tokens,
          cost_usd: message.cost_usd,
          elapsed_s: message.elapsed_s,
          fast_calls: message.fast_calls,
          fast_ms_total: message.fast_ms_total,
          text_calls: message.text_calls,
        },
      };
    case "result":
      return {
        ...state,
        result: {
          success: message.success,
          summary: message.summary,
          columns: message.columns,
          rows: message.rows,
          sources: message.sources,
          issues: message.issues,
          checklist: message.checklist ?? [],
          assumptions: message.assumptions ?? [],
          follow_ups: message.follow_ups ?? [],
        },
      };
  }
}

export function agentReducer(state: AgentState, action: AgentAction): AgentState {
  switch (action.type) {
    case "connection":
      return {
        ...state,
        connection: action.connection,
        reconnectAttempt: action.attempt ?? state.reconnectAttempt,
      };
    case "server":
      return handleServer(state, action.message);
    case "run_started":
      return {
        ...state,
        active: true,
        goal: action.goal,
        startUrl: action.startUrl,
        mode: action.mode,
        runStartedAt: action.at,
        run: "starting",
        stepNumber: 0,
        detail: action.continueSession ? "Continuing on the current page…" : "",
        plan: [],
        steps: [],
        feed: [],
        approvals: {},
        questions: {},
        frame: action.continueSession ? state.frame : null,
        stepFrames: {},
        findings: action.continueSession ? state.findings : [],
        usage: null,
        result: null,
      };
    case "load_history":
      return {
        ...state,
        active: true,
        goal: action.goal,
        startUrl: "",
        runStartedAt: null,
        run: action.status,
        stepNumber: action.stepsCount,
        detail: "Loaded from run history",
        plan: [],
        steps: [],
        feed: [],
        approvals: {},
        questions: {},
        stepFrames: {},
        findings: action.findings,
        usage: {
          llm_calls: action.stepsCount,
          input_tokens: 0,
          output_tokens: 0,
          cost_usd: action.costUsd,
          elapsed_s: action.elapsedS,
        },
        result: action.result,
      };
    case "guidance_sent":
      // Answering a question clears it; the server confirms via notices.
      return appendFeed({ ...state, questions: {} }, (key) => ({
        kind: "guidance",
        key,
        text: action.text,
      }));
    case "local_notice":
      return appendFeed(state, (key) => ({
        kind: "notice",
        key,
        level: action.level,
        message: action.message,
      }));
    case "mode_changed":
      return { ...state, mode: action.mode };
    case "reset":
      return {
        ...initialAgentState,
        connection: state.connection,
        reconnectAttempt: state.reconnectAttempt,
        session: state.session,
        mode: state.mode,
        seq: state.seq,
      };
  }
}

export function isRunFinished(run: RunState): boolean {
  return run === "done" || run === "failed" || run === "stopped";
}

export function isRunPaused(run: RunState): boolean {
  return run === "paused";
}

const SETTLED: readonly StepRecord["status"][] = ["ok", "error", "rejected", "skipped"];

// The step the agent is working on now: the newest step that has not settled,
// falling back to the newest step overall.
export function currentStep(steps: StepRecord[]): StepRecord | null {
  const open = [...steps].reverse().find((step) => !SETTLED.includes(step.status));
  return open ?? steps[steps.length - 1] ?? null;
}
