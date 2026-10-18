"use client";

import { useEffect, useState } from "react";
import { frameKey, LAST_FRAME, parseFrameKey } from "./chat-model";
import type { Frame, StepRecord } from "./protocol";
import type { ChatsApi } from "./use-chats";

interface StoredFrames {
  /** The step behind a selected "turnId::stepId" key from an earlier turn. */
  pastStep: StepRecord | null;
  /** Its saved screenshot, once loaded. */
  pastFrame: Frame | null;
  /** The last saved view of the open chat, for the browser pane when no live browser exists. */
  restoredFrame: Frame | null;
}

export function useStoredFrames(chats: ChatsApi, selectedKey: string | null, wantRestored: boolean): StoredFrames {
  const [loaded, setLoaded] = useState<{ key: string; frame: Frame | null } | null>(null);
  const [restored, setRestored] = useState<{ turnId: string; frame: Frame | null } | null>(null);
  const { loadFrame, pastTurns } = chats;

  const parsed = selectedKey ? parseFrameKey(selectedKey) : null;
  const pastStep = parsed
    ? pastTurns.find((t) => t.id === parsed.turnId)?.steps.find((s) => s.id === parsed.stepId) ?? null
    : null;

  useEffect(() => {
    if (!selectedKey || !parseFrameKey(selectedKey)) return;
    let cancelled = false;
    loadFrame(selectedKey).then((frame) => {
      if (!cancelled) setLoaded({ key: selectedKey, frame });
    });
    return () => {
      cancelled = true;
    };
  }, [selectedKey, loadFrame]);

  const lastTurn = pastTurns[pastTurns.length - 1];
  const lastTurnId = lastTurn?.id;
  const lastStepWithFrame = lastTurn?.frameSteps.filter((s) => s !== LAST_FRAME).at(-1);

  useEffect(() => {
    if (!wantRestored || !lastTurnId) return;
    let cancelled = false;
    (async () => {
      const frame =
        (await loadFrame(frameKey(lastTurnId, LAST_FRAME))) ??
        (lastStepWithFrame ? await loadFrame(frameKey(lastTurnId, lastStepWithFrame)) : null);
      if (!cancelled) setRestored({ turnId: lastTurnId, frame });
    })();
    return () => {
      cancelled = true;
    };
  }, [wantRestored, lastTurnId, lastStepWithFrame, loadFrame]);

  return {
    pastStep,
    pastFrame: loaded && loaded.key === selectedKey ? loaded.frame : null,
    restoredFrame: wantRestored && restored?.turnId === lastTurnId ? restored.frame : null,
  };
}
