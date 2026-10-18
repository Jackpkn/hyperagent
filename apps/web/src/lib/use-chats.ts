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
import type { ConversationTurn, Frame } from "./protocol";

const ACTIVE_KEY = "activeChatId";
const MEMORY_KEY = "memories";
const MIGRATED_KEY = "migratedRunHistory";
const LEGACY_HISTORY_KEY = "hyperagent.history.v1";
const SAVE_DELAY_MS = 500;

export interface ChatSummary {
  id: string;
  title: string;
  updatedAt: number;
  turns: number;
}

export interface ChatsApi {
  ready: boolean;
  persistent: boolean;
  activeChat: Chat | null;
  /** Turns of the open chat other than the one running live right now. */
  pastTurns: ChatTurn[];
  chats: ChatSummary[];
  memories: string[];
  conversation: () => ConversationTurn[];
  newChat: () => void;
  openChat: (id: string) => void;
  removeChat: (id: string) => void;
  loadFrame: (key: string) => Promise<Frame | null>;
  setMemories: (next: string[]) => void;
  rememberFromResult: (items: string[]) => string[];
}

function summarize(chats: Chat[]): ChatSummary[] {
  return chats.map((c) => ({ id: c.id, title: c.title, updatedAt: c.updatedAt, turns: c.turns.length }));
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
  const [ready, setReady] = useState(false);
  const [persistent, setPersistent] = useState(true);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [activeChat, setActiveChat] = useState<Chat | null>(null);
  const [memories, setMemoriesState] = useState<string[]>([]);
  const [liveTurnId, setLiveTurnId] = useState<string | null>(null);

  const activeRef = useRef<Chat | null>(null);
  const savedFramesRef = useRef<Set<string>>(new Set());
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingSaveRef = useRef<{ chatId: string; turn: ChatTurn } | null>(null);
  const memoriesRef = useRef<string[]>([]);

  const commit = useCallback((chat: Chat | null) => {
    activeRef.current = chat;
    setActiveChat(chat);
    if (!chat) return;
    setChats((prev) => summarize([chat]).concat(prev.filter((c) => c.id !== chat.id)));
    putChat(chat).catch(() => setPersistent(false));
  }, []);

  const flushSave = useCallback(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = null;
    const pending = pendingSaveRef.current;
    pendingSaveRef.current = null;
    const current = activeRef.current;
    if (pending && current?.id === pending.chatId) commit(upsertTurn(current, pending.turn));
  }, [commit]);

  // Load the open chat, the chat list and long-term memory once.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setPersistent(await isPersistent());
      await migrateLegacyHistory();
      const all = await listChats();
      const activeId = await getSetting<string | null>(ACTIVE_KEY);
      const saved = (await getSetting<string[]>(MEMORY_KEY)) ?? [];
      if (cancelled) return;
      const open = all.find((c) => c.id === activeId) ?? null;
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
    if (!state.runStartedAt || !state.goal) return;
    const turnId = `t-${Math.round(state.runStartedAt * 1000)}`;
    if (turnId === liveTurnId) return;
    setLiveTurnId(turnId);
    savedFramesRef.current = new Set();
    if (!activeRef.current) {
      const now = Date.now();
      const chat: Chat = { id: newId("c"), title: chatTitle(state.goal), createdAt: now, updatedAt: now, turns: [] };
      commit(chat);
      setSetting(ACTIVE_KEY, chat.id).catch(() => undefined);
    }
  }, [state.runStartedAt, state.goal, liveTurnId, commit]);

  // Screenshots have their own store; live frame arrivals must not postpone chat saves.
  useEffect(() => {
    const chat = activeRef.current;
    if (!liveTurnId || !chat || !state.goal) return;
    for (const [stepId, frame] of Object.entries(state.stepFrames)) {
      if (savedFramesRef.current.has(stepId)) continue;
      savedFramesRef.current.add(stepId);
      putFrame(chat.id, frameKey(liveTurnId, stepId), frame).catch(() => setPersistent(false));
    }
    // The final page view, kept once the run ends (live frames arrive about once a second).
    if (state.frame && isRunFinished(state.run) && !savedFramesRef.current.has(LAST_FRAME)) {
      savedFramesRef.current.add(LAST_FRAME);
      putFrame(chat.id, frameKey(liveTurnId, LAST_FRAME), state.frame).catch(() => undefined);
    }
  }, [state.stepFrames, state.frame, state.run, state.goal, liveTurnId]);

  const { goal, runStartedAt, run, mode, plan, steps, feed, findings, usage, result, stepFrames } = state;
  useEffect(() => {
    const chat = activeRef.current;
    if (!liveTurnId || !chat || !goal) return;
    pendingSaveRef.current = {
      chatId: chat.id,
      turn: snapshotTurn({ goal, runStartedAt, run, mode, plan, steps, feed, findings, usage, result },
        liveTurnId, [...savedFramesRef.current]),
    };
    // Save completed reports immediately. While running, bound the wait even during streaming text.
    if (result || isRunFinished(run)) flushSave();
    else if (!saveTimerRef.current) saveTimerRef.current = setTimeout(flushSave, SAVE_DELAY_MS);
  }, [goal, runStartedAt, run, mode, plan, steps, feed, findings, usage, result, stepFrames, liveTurnId, flushSave]);

  // Do not rely on an asynchronous IndexedDB write during page unload for important data.
  useEffect(() => {
    flushSave();
  }, [findings, plan, run, result, liveTurnId, flushSave]);

  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState === "hidden") flushSave();
    };
    window.addEventListener("pagehide", flushSave);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("pagehide", flushSave);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      flushSave();
    };
  }, [flushSave]);

  const pastTurns = (activeChat?.turns ?? []).filter((t) => t.id !== liveTurnId);

  const conversation = useCallback(
    () => summarizeConversation((activeRef.current?.turns ?? []).filter((t) => t.id !== liveTurnId)),
    [liveTurnId],
  );

  const newChat = useCallback(() => {
    flushSave();
    setLiveTurnId(null);
    activeRef.current = null;
    setActiveChat(null);
    setSetting(ACTIVE_KEY, null).catch(() => undefined);
  }, [flushSave]);

  const openChat = useCallback(
    (id: string) => {
      flushSave();
      listChats()
        .then((all) => {
          const chat = all.find((c) => c.id === id);
          if (!chat) return;
          setLiveTurnId(null);
          const settled = { ...chat, turns: chat.turns.map(settleTurn) };
          activeRef.current = settled;
          setActiveChat(settled);
          setSetting(ACTIVE_KEY, id).catch(() => undefined);
        })
        .catch(() => setPersistent(false));
    },
    [flushSave],
  );

  const removeChat = useCallback((id: string) => {
    setChats((prev) => prev.filter((c) => c.id !== id));
    if (activeRef.current?.id === id) {
      activeRef.current = null;
      setActiveChat(null);
      setLiveTurnId(null);
      setSetting(ACTIVE_KEY, null).catch(() => undefined);
    }
    deleteChat(id).catch(() => setPersistent(false));
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

  return {
    ready,
    persistent,
    activeChat,
    pastTurns,
    chats,
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
