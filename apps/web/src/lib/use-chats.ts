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
const NO_FRAMES: Record<string, Frame> = {};

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
  /** Screenshots already saved for the live turn: after a reload the replay only carries the latest one. */
  liveSavedFrames: Record<string, Frame>;
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
  const [liveSaved, setLiveSaved] = useState<{ turnId: string; frames: Record<string, Frame> } | null>(null);

  const activeRef = useRef<Chat | null>(null);
  const savedFramesRef = useRef<Set<string>>(new Set());
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const memoriesRef = useRef<string[]>([]);

  const commit = useCallback((chat: Chat | null) => {
    activeRef.current = chat;
    setActiveChat(chat);
    if (!chat) return;
    setChats((prev) => summarize([chat]).concat(prev.filter((c) => c.id !== chat.id)));
    putChat(chat).catch(() => setPersistent(false));
  }, []);

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

  // A new run is a new turn; the first turn creates the chat. Wait for the saved chats to load, so a run
  // re-attached after a reload lands in its own chat and turn instead of starting a new chat.
  useEffect(() => {
    if (!ready || !state.runStartedAt || !state.goal) return;
    const turnId = `t-${Math.round(state.runStartedAt * 1000)}`;
    if (turnId === liveTurnId) return;
    setLiveTurnId(turnId);
    // A re-attached run continues its saved turn: keep that turn's screenshots instead of starting over.
    const existing = activeRef.current?.turns.find((t) => t.id === turnId);
    const savedSteps = (existing?.frameSteps ?? []).filter((s) => s !== LAST_FRAME);
    savedFramesRef.current = new Set(savedSteps);
    setLiveSaved(null);
    const chatId = activeRef.current?.id;
    if (chatId && savedSteps.length) {
      Promise.all(savedSteps.map(async (stepId) => [stepId, await getFrame(chatId, frameKey(turnId, stepId))] as const))
        .then((pairs) => {
          const frames = Object.fromEntries(pairs.filter((pair): pair is readonly [string, Frame] => Boolean(pair[1])));
          setLiveSaved({ turnId, frames });
        })
        .catch(() => undefined);
    }
    if (!activeRef.current) {
      const now = Date.now();
      const chat: Chat = { id: newId("c"), title: chatTitle(state.goal), createdAt: now, updatedAt: now, turns: [] };
      commit(chat);
      setSetting(ACTIVE_KEY, chat.id).catch(() => undefined);
    }
  }, [ready, state.runStartedAt, state.goal, liveTurnId, commit]);

  // Save the live turn (debounced) and every new step screenshot exactly once.
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
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      const current = activeRef.current;
      if (!current) return;
      commit(upsertTurn(current, snapshotTurn(state, liveTurnId, [...savedFramesRef.current])));
    }, SAVE_DELAY_MS);
  }, [state, liveTurnId, commit]);

  useEffect(
    () => () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    },
    [],
  );

  const pastTurns = (activeChat?.turns ?? []).filter((t) => t.id !== liveTurnId);
  const liveSavedFrames = liveSaved && liveSaved.turnId === liveTurnId ? liveSaved.frames : NO_FRAMES;

  const conversation = useCallback(
    () => summarizeConversation((activeRef.current?.turns ?? []).filter((t) => t.id !== liveTurnId)),
    [liveTurnId],
  );

  const newChat = useCallback(() => {
    setLiveTurnId(null);
    activeRef.current = null;
    setActiveChat(null);
    setSetting(ACTIVE_KEY, null).catch(() => undefined);
  }, []);

  const openChat = useCallback(
    (id: string) => {
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
    [],
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
    liveSavedFrames,
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
