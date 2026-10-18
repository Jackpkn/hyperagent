"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import type { ApprovalMode, ClientMessage, ConversationTurn } from "./protocol";
import { parseServerMessage } from "./protocol";
import { agentReducer, initialAgentState, isRunFinished } from "./agent-state";
import type { AgentState } from "./agent-state";
import { getWsUrl } from "./ws-url";

const BASE_DELAY_MS = 800;
const MAX_DELAY_MS = 8000;
const RESUME_KEY = "hyperagent.resume";

/** The run this tab started, so a reload can re-attach to it while the server keeps it going. */
interface ResumeRecord {
  token: string;
  goal: string;
  startUrl: string;
  mode: ApprovalMode;
  at: number;
}

// Session storage: survives a reload of this tab, never shared with other tabs.
function readResume(): ResumeRecord | null {
  try {
    const raw = window.sessionStorage.getItem(RESUME_KEY);
    const data = raw ? (JSON.parse(raw) as ResumeRecord) : null;
    return data && typeof data.token === "string" && typeof data.at === "number" ? data : null;
  } catch {
    return null;
  }
}

function writeResume(record: ResumeRecord | null): void {
  try {
    if (record) window.sessionStorage.setItem(RESUME_KEY, JSON.stringify(record));
    else window.sessionStorage.removeItem(RESUME_KEY);
  } catch {
    // Without storage a reload simply cannot re-attach; the run itself is unaffected.
  }
}

export interface StartOptions {
  goal: string;
  startUrl: string;
  mode: ApprovalMode;
  model: string;
  continueSession?: boolean;
  persistSession?: boolean;
  operatorContext?: string;
  /** Earlier turns of the open chat, condensed, so follow-ups can refer to them. */
  conversation?: ConversationTurn[];
  /** Long-term memory items applied to every run. */
  userMemory?: string[];
}

export interface AgentApi {
  state: AgentState;
  startRun: (options: StartOptions) => boolean;
  send: (message: ClientMessage) => boolean;
  guide: (text: string, pin?: { x: number; y: number } | null) => boolean;
  changeMode: (mode: ApprovalMode) => boolean;
  reconnectNow: () => void;
  reset: () => void;
  notify: (level: "info" | "warn" | "error", message: string) => void;
}

function backoffDelay(attempt: number): number {
  return Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** Math.min(attempt, 6));
}

export function useAgent(): AgentApi {
  const [state, dispatch] = useReducer(agentReducer, initialAgentState);
  const socketRef = useRef<WebSocket | null>(null);
  const attemptRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedByUnmountRef = useRef(false);
  const connectRef = useRef<() => void>(() => undefined);
  // Resume token of the session behind the current socket.
  const tokenRef = useRef<string | null>(null);

  useEffect(() => {
    closedByUnmountRef.current = false;

    const scheduleReconnect = () => {
      if (closedByUnmountRef.current) return;
      const delay = backoffDelay(attemptRef.current);
      attemptRef.current += 1;
      dispatch({ type: "connection", connection: "reconnecting", attempt: attemptRef.current });
      timerRef.current = setTimeout(() => connectRef.current(), delay);
    };

    const connect = () => {
      if (closedByUnmountRef.current) return;
      let socket: WebSocket;
      try {
        socket = new WebSocket(getWsUrl());
      } catch {
        scheduleReconnect();
        return;
      }
      socketRef.current = socket;

      socket.onopen = () => {
        attemptRef.current = 0;
        dispatch({ type: "connection", connection: "open", attempt: 0 });
      };
      socket.onmessage = (event: MessageEvent) => {
        if (typeof event.data !== "string") return;
        const message = parseServerMessage(event.data);
        if (!message) return;
        if (message.type === "hello") {
          tokenRef.current = message.resume_token ?? null;
          // A fresh session after a reload or dropped connection: ask for the run this tab started.
          const saved = readResume();
          if (saved && saved.token !== message.resume_token) {
            socket.send(JSON.stringify({ type: "attach", token: saved.token } satisfies ClientMessage));
          }
        } else if (message.type === "attached") {
          const saved = readResume();
          if (saved) {
            // Rebuild the view from scratch; the replayed messages that follow fill it in.
            dispatch({ type: "run_started", goal: saved.goal, startUrl: saved.startUrl,
              mode: message.approval_mode, at: saved.at });
          }
        } else if (message.type === "attach_failed") {
          writeResume(null);
        } else if (message.type === "status" && isRunFinished(message.state)) {
          writeResume(null);
        }
        dispatch({ type: "server", message });
      };
      socket.onclose = () => {
        // A socket replaced or closed by the effect cleanup must not reconnect.
        if (socketRef.current !== socket) return;
        socketRef.current = null;
        scheduleReconnect();
      };
      // onerror is always followed by onclose, which handles the retry.
      socket.onerror = () => undefined;
    };

    connectRef.current = connect;
    connect();

    return () => {
      closedByUnmountRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      const socket = socketRef.current;
      socketRef.current = null;
      socket?.close();
    };
  }, []);

  const send = useCallback((message: ClientMessage): boolean => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      dispatch({
        type: "local_notice",
        level: "warn",
        message: "Not connected to the agent server. Your message was not sent.",
      });
      return false;
    }
    socket.send(JSON.stringify(message));
    return true;
  }, []);

  const startRun = useCallback(
    (options: StartOptions): boolean => {
      const goal = options.goal.trim();
      if (!goal) return false;
      const startUrl = options.startUrl.trim();
      const operatorContext = options.operatorContext?.trim();
      const payload: ClientMessage = {
        type: "start",
        goal,
        approval_mode: options.mode,
        ...(startUrl ? { start_url: startUrl } : {}),
        ...(options.model ? { model: options.model } : {}),
        ...(options.continueSession ? { continue_session: true } : {}),
        ...(options.persistSession ? { persist_session: true } : {}),
        ...(operatorContext ? { operator_context: operatorContext } : {}),
        ...(options.conversation?.length ? { conversation: options.conversation } : {}),
        ...(options.userMemory?.length ? { user_memory: options.userMemory } : {}),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      };
      const sent = send(payload);
      if (!sent) return false;
      const at = Date.now() / 1000;
      if (tokenRef.current) writeResume({ token: tokenRef.current, goal, startUrl, mode: options.mode, at });
      dispatch({
        type: "run_started",
        goal,
        startUrl,
        mode: options.mode,
        at,
        continueSession: options.continueSession,
      });
      return true;
    },
    [send],
  );

  const guide = useCallback(
    (text: string, pin?: { x: number; y: number } | null): boolean => {
      const trimmed = text.trim();
      if (!trimmed) return false;
      const payload: ClientMessage = pin
        ? { type: "guide", text: trimmed, pin_x: pin.x, pin_y: pin.y }
        : { type: "guide", text: trimmed };
      if (!send(payload)) return false;
      const display = pin ? `📍 Pinned (${pin.x}, ${pin.y}) · ${trimmed}` : trimmed;
      dispatch({ type: "guidance_sent", text: display });
      return true;
    },
    [send],
  );

  const changeMode = useCallback(
    (mode: ApprovalMode): boolean => {
      if (!send({ type: "set_mode", approval_mode: mode })) return false;
      dispatch({ type: "mode_changed", mode });
      return true;
    },
    [send],
  );

  const reconnectNow = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (socketRef.current) return;
    attemptRef.current = 0;
    connectRef.current();
  }, []);

  const reset = useCallback(() => dispatch({ type: "reset" }), []);

  const notify = useCallback((level: "info" | "warn" | "error", message: string) => {
    dispatch({ type: "local_notice", level, message });
  }, []);

  return { state, startRun, send, guide, changeMode, reconnectNow, reset, notify };
}
