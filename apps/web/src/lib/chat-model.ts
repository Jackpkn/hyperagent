import type { AgentState, FeedItem } from "./agent-state";
import type {
  ApprovalMode,
  ConversationTurn,
  Finding,
  PlanItem,
  RunResult,
  RunState,
  StepRecord,
  Usage,
} from "./protocol";
import { formatCell } from "./format";

/** One question and the run that answered it. Screenshots live in a separate store, keyed by frameKey(). */
export interface ChatTurn {
  id: string;
  goal: string;
  startedAt: number; // epoch seconds
  run: RunState;
  mode: ApprovalMode;
  plan: PlanItem[];
  steps: StepRecord[];
  feed: FeedItem[];
  findings: Finding[];
  usage: Usage | null;
  result: RunResult | null;
  /** Step ids that have a stored screenshot, so Inspect buttons render without loading images. */
  frameSteps: string[];
}

export interface Chat {
  id: string;
  title: string;
  createdAt: number; // epoch ms
  updatedAt: number; // epoch ms
  turns: ChatTurn[];
}

const TERMINAL: RunState[] = ["done", "failed", "stopped"];
const DETAILED_TURNS = 2;
const MAX_ROWS = 15;
const OLDER_ANSWER_CHARS = 160;
const RECENT_ANSWER_CHARS = 700;
export const MAX_MEMORIES = 20;
export const MAX_MEMORY_CHARS = 200;

export const LAST_FRAME = "last";

export function frameKey(turnId: string, stepId: string): string {
  return `${turnId}::${stepId}`;
}

export function parseFrameKey(key: string): { turnId: string; stepId: string } | null {
  const at = key.indexOf("::");
  return at > 0 ? { turnId: key.slice(0, at), stepId: key.slice(at + 2) } : null;
}

export function newId(prefix: string): string {
  const random = Math.random().toString(36).slice(2, 8);
  return `${prefix}-${Date.now().toString(36)}-${random}`;
}

export function chatTitle(goal: string): string {
  const flat = goal.replace(/\s+/g, " ").trim();
  return flat.length > 60 ? `${flat.slice(0, 59)}…` : flat || "New chat";
}

/** The live run as a storable turn (immutable copy of the parts worth keeping). */
export function snapshotTurn(state: AgentState, turnId: string, frameSteps: string[]): ChatTurn {
  return {
    id: turnId,
    goal: state.goal,
    startedAt: state.runStartedAt ?? Date.now() / 1000,
    run: state.run,
    mode: state.mode,
    plan: state.plan,
    steps: state.steps,
    feed: state.feed,
    findings: state.findings,
    usage: state.usage,
    result: state.result,
    frameSteps,
  };
}

/** A turn saved mid-run cannot continue after a reload: show it as stopped, not as forever "thinking". */
export function settleTurn(turn: ChatTurn): ChatTurn {
  if (TERMINAL.includes(turn.run)) return turn;
  const steps = turn.steps.map((s) =>
    ["ok", "error", "rejected", "skipped"].includes(s.status)
      ? s
      : { ...s, status: "skipped" as const, result: "Interrupted when the page was reloaded." },
  );
  return { ...turn, run: "stopped", steps };
}

export function upsertTurn(chat: Chat, turn: ChatTurn): Chat {
  const exists = chat.turns.some((t) => t.id === turn.id);
  const turns = exists ? chat.turns.map((t) => (t.id === turn.id ? turn : t)) : [...chat.turns, turn];
  return { ...chat, turns, updatedAt: Date.now() };
}

function firstSentence(text: string, max: number): string {
  const flat = text.replace(/[#*_`>|]/g, " ").replace(/\s+/g, " ").trim();
  const sentence = flat.match(/^.*?[.!?](\s|$)/)?.[0]?.trim() ?? flat;
  return sentence.length > max ? `${sentence.slice(0, max - 1)}…` : sentence;
}

/**
 * Earlier turns condensed for a follow-up question: the latest turns in detail (answer + table rows),
 * older ones as a single line, so a long chat does not make every step expensive.
 */
export function summarizeConversation(turns: ChatTurn[]): ConversationTurn[] {
  const answered = turns.filter((t) => t.goal.trim());
  return answered.slice(-12).map((turn, index, list) => {
    const recent = index >= list.length - DETAILED_TURNS;
    const summary = turn.result?.summary ?? "";
    const answer = turn.result
      ? recent
        ? summary.replace(/\s+/g, " ").trim().slice(0, RECENT_ANSWER_CHARS)
        : firstSentence(summary, OLDER_ANSWER_CHARS)
      : `(no answer: the run ${turn.run === "stopped" ? "was stopped" : "ended early"})`;
    const base: ConversationTurn = { goal: turn.goal.slice(0, 1000), answer };
    if (!recent || !turn.result || turn.result.rows.length === 0) return base;
    const columns = turn.result.columns.slice(0, 12);
    const rows = turn.result.rows.slice(0, MAX_ROWS).map((row) =>
      Object.fromEntries(columns.map((c) => [c.slice(0, 200), formatCell(row[c]).slice(0, 300)])),
    );
    return { ...base, columns, rows };
  });
}

export function addMemories(current: string[], incoming: string[]): string[] {
  const seen = new Set(current.map((m) => m.toLowerCase()));
  const fresh = incoming
    .map((m) => m.trim().slice(0, MAX_MEMORY_CHARS))
    .filter((m) => m && !seen.has(m.toLowerCase()));
  return [...current, ...fresh].slice(-MAX_MEMORIES);
}
