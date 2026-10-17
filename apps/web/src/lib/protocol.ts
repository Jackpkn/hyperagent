// Types mirroring docs/protocol.md. Keep in sync with the server contract.

export type ApprovalMode = "risky" | "always" | "never";

export type RunState =
  | "idle"
  | "starting"
  | "running"
  | "thinking"
  | "acting"
  | "paused"
  | "awaiting_approval"
  | "awaiting_user"
  | "finishing"
  | "done"
  | "failed"
  | "stopped";

export type StepStatus =
  | "thinking"
  | "planned"
  | "awaiting_approval"
  | "running"
  | "ok"
  | "error"
  | "rejected"
  | "skipped";

export type PlanStatus = "pending" | "active" | "done" | "skipped";

export type NoticeLevel = "info" | "warn" | "error";

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Thought {
  evaluation: string;
  memory: string;
  next_goal: string;
}

export interface StepAction {
  name: string;
  args: Record<string, unknown>;
  label: string;
}

export interface StepTarget {
  label: string;
  rect?: Rect;
}

export interface StepRisk {
  risky: boolean;
  reason: string;
}

export interface StepRecord {
  id: string;
  n: number;
  status: StepStatus;
  thought?: Thought;
  action?: StepAction;
  target?: StepTarget;
  risk?: StepRisk;
  result?: string;
  error?: string;
  url?: string;
  started_at: number;
  ended_at?: number;
  /** "planner" = System 2 LLM, "fast" = System 1 (TypeSafe Jev). */
  system?: "planner" | "fast";
  /** Id of the planner step that delegated this fast step. */
  parent?: string;
  confidence?: number;
  alternatives?: { label: string; p: number }[];
  latency_ms?: number;
}

export interface PlanItem {
  text: string;
  status: PlanStatus;
}

export interface Finding {
  source_url: string;
  data: Record<string, unknown>;
}

export interface Approval {
  step_id: string;
  reason: string;
  action_label: string;
  target_label?: string;
  args: Record<string, unknown>;
}

export interface Question {
  step_id: string;
  question: string;
}

export interface Usage {
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  elapsed_s: number;
  fast_calls?: number;
  fast_ms_total?: number;
  text_calls?: number;
}

export interface SourceLink {
  title: string;
  url: string;
}

export interface RunResult {
  success: boolean;
  summary: string;
  columns: string[];
  rows: Record<string, unknown>[];
  sources: SourceLink[];
  issues: string[];
}

export interface TabInfo {
  index: number;
  title: string;
  url: string;
  active: boolean;
}

export interface Frame {
  image: string;
  url: string;
  title: string;
  w: number;
  h: number;
  tabs: TabInfo[];
}

export interface Hello {
  session_id: string;
  model: string;
  models: string[];
  max_steps: number;
  /** TypeSafe model used for System 1, or null when the fast policy is not configured. */
  fast_model?: string | null;
  has_saved_session?: boolean;
}

export interface StatusMessage {
  state: RunState;
  step: number;
  detail?: string;
}

// Server -> client

export type ServerMessage =
  | ({ type: "hello" } & Hello)
  | ({ type: "status" } & StatusMessage)
  | ({ type: "frame" } & Frame)
  | ({ type: "step" } & StepRecord)
  | { type: "plan"; items: PlanItem[] }
  | { type: "findings"; items: Finding[] }
  | ({ type: "approval" } & Approval)
  | ({ type: "question" } & Question)
  | { type: "notice"; level: NoticeLevel; message: string }
  | ({ type: "usage" } & Usage)
  | ({ type: "result" } & RunResult);

// Client -> server

export type ClientMessage =
  | {
      type: "start";
      goal: string;
      start_url?: string;
      approval_mode?: ApprovalMode;
      model?: string;
      /** IANA time zone of the operator, so "today" means their today. */
      timezone?: string;
      continue_session?: boolean;
      persist_session?: boolean;
      operator_context?: string;
    }
  | { type: "pause" }
  | { type: "resume" }
  | { type: "stop" }
  | { type: "guide"; text: string; pin_x?: number; pin_y?: number }
  | { type: "approve"; step_id: string }
  | { type: "reject"; step_id: string; reason?: string }
  | { type: "set_mode"; approval_mode: ApprovalMode }
  | { type: "takeover_click"; x: number; y: number }
  | { type: "takeover_type"; text: string; press_enter?: boolean }
  | { type: "takeover_scroll"; dy: number }
  | { type: "takeover_tab"; tab_index: number }
  | { type: "save_session" }
  | { type: "clear_session" };

const RUN_STATES: readonly RunState[] = [
  "idle",
  "starting",
  "running",
  "thinking",
  "acting",
  "paused",
  "awaiting_approval",
  "awaiting_user",
  "finishing",
  "done",
  "failed",
  "stopped",
];

export function isRunState(value: unknown): value is RunState {
  return typeof value === "string" && (RUN_STATES as readonly string[]).includes(value);
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// Parse a raw socket payload. Returns null for anything that is not a known,
// minimally well-formed server message, so bad input never reaches the reducer.
export function parseServerMessage(raw: string): ServerMessage | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(data) || typeof data.type !== "string") return null;

  switch (data.type) {
    case "hello":
    case "status":
    case "frame":
    case "step":
    case "plan":
    case "findings":
    case "approval":
    case "question":
    case "notice":
    case "usage":
    case "result":
      if (data.type === "status" && !isRunState(data.state)) return null;
      if (data.type === "step" && (typeof data.id !== "string" || typeof data.n !== "number")) {
        return null;
      }
      return data as unknown as ServerMessage;
    default:
      return null;
  }
}
