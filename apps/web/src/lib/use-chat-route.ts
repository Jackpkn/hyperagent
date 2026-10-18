"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { isRunFinished } from "./agent-state";
import { chatIdFromPath, chatPath } from "./chat-path";
import type { AgentApi } from "./use-agent";
import type { ChatsApi } from "./use-chats";

type Destination = { id: string | null; history: "push" | "pop" | "replace"; deleteId?: string };

export function useChatRoute(agent: AgentApi, chats: ChatsApi) {
  const { state, send, reset } = agent;
  const { ready, flush, openChat, newChat, removeChat } = chats;
  const activeId = chats.activeChat?.id ?? null;
  const [destination, setDestination] = useState<Destination | null>(null);
  const destinationRef = useRef<Destination | null>(null);
  const stoppingRef = useRef(false);
  const busy = state.run !== "idle" && !isRunFinished(state.run);

  const navigate = useCallback((id: string | null, history: Destination["history"] = "push", deleteId?: string) => {
    if (id && id === activeId && !destinationRef.current) return;
    const next = { id, history, deleteId };
    destinationRef.current = next;
    setDestination(next);
    if (busy && !stoppingRef.current) {
      stoppingRef.current = true;
      if (!send({ type: "stop" })) {
        stoppingRef.current = false;
        destinationRef.current = null;
        setDestination(null);
        window.history.replaceState(null, "", chatPath(activeId));
      }
    }
  }, [activeId, busy, send]);

  const navigateRef = useRef(navigate);
  useEffect(() => { navigateRef.current = navigate; }, [navigate]);
  useEffect(() => {
    const onPop = () => navigateRef.current(chatIdFromPath(window.location.pathname), "pop");
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    if (!destination || !ready || busy) return;
    let cancelled = false;
    const controller = new AbortController();
    void (async () => {
      // Include the terminal result before resetting the live state or selecting another owner.
      await flush();
      if (cancelled || destinationRef.current !== destination) return;
      reset();
      if (destination.id) await openChat(destination.id, controller.signal);
      else newChat();
      if (cancelled || destinationRef.current !== destination) return;
      if (destination.deleteId) await removeChat(destination.deleteId);
      if (cancelled || destinationRef.current !== destination) return;
      const path = chatPath(destination.id);
      if (destination.history !== "pop" && window.location.pathname !== path) {
        if (destination.history === "replace") window.history.replaceState(null, "", path);
        else window.history.pushState(null, "", path);
      }
      stoppingRef.current = false;
      destinationRef.current = null;
      setDestination(null);
    })();
    return () => { cancelled = true; controller.abort(); };
  }, [destination, ready, busy, flush, openChat, newChat, removeChat, reset]);

  useEffect(() => {
    if (!ready || destination || !activeId || !state.runStartedAt) return;
    const path = chatPath(activeId);
    if (window.location.pathname !== path) window.history.pushState(null, "", path);
  }, [ready, destination, activeId, state.runStartedAt]);

  return { navigate, switching: destination !== null, stopping: destination !== null && busy };
}
