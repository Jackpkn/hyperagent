"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { isRunFinished, type AgentState } from "./agent-state";
import {
  addMemories,
  chatTitle,
  frameKey,
  LAST_FRAME,
  newId,
  settleTurn,
  snapshotTurn,
  summarizeConversation,
  upsertTurn,
  type Chat,
  type ChatTurn,
} from "./chat-model";
import {
  deleteChat,
  getFrame,
  getSetting,
  isPersistent,
  listChats,
  putChat,
  putFrame,
  setSetting,
} from "./chat-db";
import { chatIdFromPath } from "./chat-path";
import type { ConversationTurn, Frame, Usage } from "./protocol";
import { sumUsage } from "./usage";

const MEMORY_KEY = "memories";
const MIGRATED_KEY = "migratedRunHistory";
const LEGACY_HISTORY_KEY = "hyperagent.history.v1";
const SAVE_DELAY_MS = 500;

export interface ChatSummary {
  id: string;
  title: string;
  updatedAt: number;
  turns: number;
  usage: Usage;
}

export interface ChatsApi {
  ready: boolean;
  error: string | null;
  flush: () => Promise<void>;
  persistent: boolean;
  activeChat: Chat | null;
  /** Turns of the open chat other than the one running live right now. */
  pastTurns: ChatTurn[];
  chats: ChatSummary[];
  chatUsage: Usage;
  allChatsUsage: Usage;
  memories: string[];
  conversation: () => ConversationTurn[];
  newChat: () => void;
  openChat: (id: string, signal?: AbortSignal) => Promise<boolean>;
  removeChat: (id: string) => Promise<boolean>;
  loadFrame: (key: string) => Promise<Frame | null>;
  setMemories: (next: string[]) => void;
  rememberFromResult: (items: string[]) => string[];
}

function summarize(chats: Chat[]): ChatSummary[] {
  return chats.map((c) => ({ id: c.id, title: c.title, updatedAt: c.updatedAt, turns: c.turns.length,
    usage: sumUsage(c.turns.map((turn) => turn.usage)) }));
}

/** One-time import of the old summary-only run history, as single-turn chats without screenshots. */
async function migrateLegacyHistory(): Promise<void> {
  if (await getSetting<boolean>(MIGRATED_KEY)) return;
  try {
    const raw = window.localStorage.getItem(LEGACY_HISTORY_KEY);
    const entries = raw ? (JSON.parse(raw) as Array<Record<string, unknown>>) : [];
    for (const e of Array.isArray(entries) ? entries : []) {
      const goal = String(e.goal ?? "");
      const createdAt = Number(e.createdAt) || Date.now();
      const turn: ChatTurn = {
        id: newId("t"),
        goal,
        startedAt: createdAt / 1000,
        run: (e.status as ChatTurn["run"]) ?? "done",
        mode: "risky",
        plan: [],
        steps: [],
        feed: [],
        findings: (e.findings as ChatTurn["findings"]) ?? [],
        usage: null,
        result: (e.result as ChatTurn["result"]) ?? null,
        frameSteps: [],
      };
      await putChat({ id: newId("c"), title: chatTitle(goal), createdAt, updatedAt: createdAt, turns: [turn] });
    }
  } catch {
    // A corrupt legacy entry is skipped; the new store is unaffected.
  }
  await setSetting(MIGRATED_KEY, true);
}

export function useChats(state: AgentState): ChatsApi {
  const [error, setError] = useState<string | null>(null);
  const pendingSaveRef = useRef<Chat | null>(null);
  const savePromiseRef = useRef<Promise<void>>(Promise.resolve());
  const [ready, setReady] = useState(false);
  const [persistent, setPersistent] = useState(true);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [activeChat, setActiveChat] = useState<Chat | null>(null);
  const [memories, setMemoriesState] = useState<string[]>([]);
  const [liveTurnId, setLiveTurnId] = useState<string | null>(null);

  const activeRef = useRef<Chat | null>(null);
  const savedFramesRef = useRef<Set<string>>(new Set());
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const memoriesRef = useRef<string[]>([]);

  const commit = useCallback((chat: Chat | null) => {
    activeRef.current = chat;
    setActiveChat(chat);
    if (!chat) return;
    setChats((prev) => summarize([chat]).concat(prev.filter((c) => c.id !== chat.id)));
    savePromiseRef.current = putChat(chat).catch(() => setPersistent(false));
  }, []);

  const flush = useCallback(async () => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    const pending = pendingSaveRef.current;
    pendingSaveRef.current = null;
    if (pending) commit(pending);
    await savePromiseRef.current;
  }, [commit]);

  // The URL, rather than the last-opened chat setting, determines what opens.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setPersistent(await isPersistent());
      await migrateLegacyHistory();
      const all = await listChats();
      const activeId = chatIdFromPath(window.location.pathname);
      const saved = (await getSetting<string[]>(MEMORY_KEY)) ?? [];
      if (cancelled) return;
      const open = all.find((c) => c.id === activeId) ?? null;
      if (activeId && !open) setError("This chat is not available in this browser. It may have been deleted or saved on another device.");
      const settled = open ? { ...open, turns: open.turns.map(settleTurn) } : null;
      activeRef.current = settled;
      memoriesRef.current = saved;
      setChats(summarize(all));
      setActiveChat(settled);
      setMemoriesState(saved);
      setReady(true);
    })().catch(() => {
      if (!cancelled) {
        setPersistent(false);
        setReady(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // A new run is a new turn; the first turn creates the chat.
  useEffect(() => {
    if (!ready || !state.runStartedAt || !state.goal) return;
    const turnId = `t-${Math.round(state.runStartedAt * 1000)}`;
    if (turnId === liveTurnId) return;
    setLiveTurnId(turnId);
    savedFramesRef.current = new Set();
    if (!activeRef.current) {
      const now = Date.now();
      const chat: Chat = { id: newId("c"), title: chatTitle(state.goal), createdAt: now, updatedAt: now, turns: [] };
      commit(upsertTurn(chat, snapshotTurn(state, turnId, [])));
    }
  }, [state, ready, liveTurnId, commit]);

  // Save the live turn (debounced) and every new step screenshot exactly once.
  useEffect(() => {
    const chat = activeRef.current;
    if (!liveTurnId || !chat || !state.goal || liveTurnId !== `t-${Math.round((state.runStartedAt ?? 0) * 1000)}`) return;
    for (const [stepId, frame] of Object.entries(state.stepFrames)) {
      if (savedFramesRef.current.has(stepId)) continue;
      savedFramesRef.current.add(stepId);
      putFrame(chat.id, frameKey(liveTurnId, stepId), frame).catch(() => setPersistent(false));
    }
    // The final page view, kept once the run ends (live frames arrive about once a second).
    if (state.frame && isRunFinished(state.run) && !savedFramesRef.current.has(LAST_FRAME)) {
      savedFramesRef.current.add(LAST_FRAME);
      putFrame(chat.id, frameKey(liveTurnId, LAST_FRAME), state.frame).catch(() => setPersistent(false));
    }
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    // Capture the owner now: a delayed save must never write into a newly selected chat.
    const next = upsertTurn(chat, snapshotTurn(state, liveTurnId, [...savedFramesRef.current]));
    pendingSaveRef.current = next;
    if (isRunFinished(state.run)) {
      void flush();
    } else {
      saveTimerRef.current = setTimeout(() => void flush(), SAVE_DELAY_MS);
    }
  }, [state, liveTurnId, flush]);

  useEffect(() => {
    const save = () => { void flush(); };
    window.addEventListener("pagehide", save);
    return () => {
      window.removeEventListener("pagehide", save);
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [flush]);

  const pastTurns = (activeChat?.turns ?? []).filter((t) => t.id !== liveTurnId);

  const conversation = useCallback(
    () => summarizeConversation((activeRef.current?.turns ?? []).filter((t) => t.id !== liveTurnId)),
    [liveTurnId],
  );

  const newChat = useCallback(() => {
    setLiveTurnId(null);
    activeRef.current = null;
    setActiveChat(null);
    setError(null);
  }, []);

  const openChat = useCallback(async (id: string, signal?: AbortSignal): Promise<boolean> => {
    try {
      // Another tab may have edited or deleted this record since the sidebar loaded.
      const all = await listChats();
      if (signal?.aborted) return false;
      const chat = all.find((item) => item.id === id);
      setChats(summarize(all));
      setLiveTurnId(null);
      if (!chat) {
        activeRef.current = null;
        setActiveChat(null);
        setError("This chat is not available in this browser. It may have been deleted or saved on another device.");
        return false;
      }
      const settled = { ...chat, turns: chat.turns.map(settleTurn) };
      activeRef.current = settled;
      setActiveChat(settled);
      setError(null);
      return true;
    } catch {
      if (!signal?.aborted) {
        activeRef.current = null;
        setActiveChat(null);
        setLiveTurnId(null);
        setPersistent(false);
        setError("Could not open this saved chat. Reload the page and try again.");
      }
      return false;
    }
  }, []);

  const removeChat = useCallback(async (id: string): Promise<boolean> => {
    if (pendingSaveRef.current?.id === id) {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      pendingSaveRef.current = null;
    }
    try {
      // Do not finish navigation (or remove the row) before the storage transaction commits.
      await deleteChat(id);
      setChats((prev) => prev.filter((c) => c.id !== id));
      if (activeRef.current?.id === id) {
        activeRef.current = null;
        setActiveChat(null);
        setLiveTurnId(null);
      }
      return true;
    } catch {
      setPersistent(false);
      setError("Could not delete the saved chat from this browser. Reload and try again.");
      return false;
    }
  }, []);

  const loadFrame = useCallback((key: string) => {
    const chat = activeRef.current;
    return chat ? getFrame(chat.id, key).catch(() => null) : Promise.resolve(null);
  }, []);

  const setMemories = useCallback((next: string[]) => {
    memoriesRef.current = next;
    setMemoriesState(next);
    setSetting(MEMORY_KEY, next).catch(() => setPersistent(false));
  }, []);

  const rememberFromResult = useCallback(
    (items: string[]) => {
      const next = addMemories(memoriesRef.current, items);
      const added = next.filter((m) => !memoriesRef.current.includes(m));
      if (added.length) setMemories(next);
      return added;
    },
    [setMemories],
  );

  // Replace the saved snapshot of the live turn instead of counting it twice.
  const currentTurnId = state.active && state.runStartedAt
    ? `t-${Math.round(state.runStartedAt * 1000)}` : null;
  const chatUsage = sumUsage([
    ...(activeChat?.turns ?? []).filter((turn) => turn.id !== currentTurnId).map((turn) => turn.usage),
    currentTurnId ? state.usage : null,
  ]);
  const allChatsUsage = sumUsage([
    ...chats.filter((chat) => chat.id !== activeChat?.id).map((chat) => chat.usage),
    chatUsage,
  ]);

  return {
    ready,
    error,
    flush,
    persistent,
    activeChat,
    pastTurns,
    chats,
    chatUsage,
    allChatsUsage,
    memories,
    conversation,
    newChat,
    openChat,
    removeChat,
    loadFrame,
    setMemories,
    rememberFromResult,
  };
}
