"use client";

import { useRef, useState, type MouseEvent, type WheelEvent } from "react";
import {
  ArrowDown,
  ArrowUp,
  BookmarkCheck,
  CornerDownLeft,
  Crosshair,
  ExternalLink,
  Globe,
  Hand,
  History,
  Keyboard,
  Lock,
  Monitor,
  Radio,
  X,
} from "lucide-react";
import type { Frame, Rect } from "@/lib/protocol";

export interface BrowserTarget {
  label: string;
  rect?: Rect;
  // Overlay action label shown above the box, e.g. 'Click "Search"'.
  action: string;
  risky: boolean;
  recent?: boolean;
}

interface BrowserViewProps {
  frame: Frame | null;
  target: BrowserTarget | null;
  statusText: string;
  paused: boolean;
  takeoverEnabled: boolean;
  /** Why the page cannot be scrolled or clicked right now, shown briefly when the operator tries. */
  blockedHint?: string;
  subtitle: string;
  hasSavedSession?: boolean;
  timeTravelStep?: { n: number; label: string } | null;
  onExitTimeTravel?: () => void;
  pinMode?: boolean;
  pinnedPoint?: { x: number; y: number } | null;
  onTogglePinMode?: () => void;
  onPinPoint?: (pt: { x: number; y: number } | null) => void;
  onClick: (x: number, y: number) => void;
  onType: (text: string, pressEnter: boolean) => void;
  onScroll: (dy: number) => void;
  onSwitchTab?: (tabIndex: number) => void;
  onSaveSession?: () => void;
}

const HINT_MS = 2500;

function isSecureUrl(url?: string): boolean {
  return Boolean(url && /^https:\/\//i.test(url));
}

function isWebUrl(url?: string): boolean {
  return Boolean(url && /^https?:\/\//i.test(url));
}

export function BrowserView({
  frame,
  target,
  statusText,
  paused,
  takeoverEnabled,
  blockedHint,
  hasSavedSession,
  timeTravelStep,
  onExitTimeTravel,
  pinMode,
  pinnedPoint,
  onTogglePinMode,
  onPinPoint,
  onClick,
  onType,
  onScroll,
  onSwitchTab,
  onSaveSession,
}: BrowserViewProps) {
  const hasUrl = Boolean(frame?.url);

  return (
    <section className="browser-stage" aria-label="Live browser viewport">
      <div className="chrome">
        <div className="chrome-bar">
          <div className="traffic" aria-hidden="true">
            <span className="traffic-dot traffic-close" />
            <span className="traffic-dot traffic-min" />
            <span className="traffic-dot traffic-max" />
          </div>

          <div className="url-bar">
            <span className="url-icon" aria-hidden="true">
              {isSecureUrl(frame?.url) ? <Lock size={12} /> : <Globe size={12} />}
            </span>
            <span className="url-text" title={frame?.url ?? ""}>
              {frame?.url || "Waiting for browser navigation…"}
            </span>
            {hasUrl && isWebUrl(frame?.url) ? (
              <a
                href={frame?.url}
                target="_blank"
                rel="noopener noreferrer"
                className="url-open-link"
                title="Open URL in a new tab"
                aria-label="Open current URL in a new tab"
              >
                <ExternalLink size={12} />
              </a>
            ) : null}
          </div>

          {frame && onTogglePinMode && !timeTravelStep ? (
            <button
              type="button"
              className={`pin-mode-btn${pinMode || pinnedPoint ? " is-active" : ""}`}
              onClick={onTogglePinMode}
              title="Point & Steer: click an element on the page to pin it to your next guidance message (or Alt+click anytime)"
            >
              <Crosshair size={12} aria-hidden="true" />
              <span>{pinnedPoint ? "Pinned" : pinMode ? "Click page…" : "Pin target"}</span>
            </button>
          ) : null}

          <div className="chrome-status" aria-live="polite">
            <span
              className={`dot ${timeTravelStep ? "dot-wait" : paused ? "dot-wait" : target ? "dot-live" : "dot-open"}`}
              aria-hidden="true"
            />
            <span className="chrome-status-text">
              {timeTravelStep ? `Step #${timeTravelStep.n} snapshot` : statusText}
            </span>
          </div>
        </div>

        {timeTravelStep ? (
          <div className="time-travel-banner" role="status">
            <div className="time-travel-info">
              <History size={13} aria-hidden="true" />
              <span>
                Time-traveling: <strong>Step #{timeTravelStep.n}</strong>
                {timeTravelStep.label ? ` · ${timeTravelStep.label}` : ""}
              </span>
            </div>
            {onExitTimeTravel ? (
              <button type="button" className="btn btn-primary btn-sm" onClick={onExitTimeTravel}>
                <Radio size={12} aria-hidden="true" />
                <span>Back to Live</span>
              </button>
            ) : null}
          </div>
        ) : null}

        {frame && frame.tabs.length > 1 && !timeTravelStep ? (
          <div className="tabs" role="tablist" aria-label="Open tabs">
            {frame.tabs.map((tab) => (
              <button
                key={tab.index}
                type="button"
                role="tab"
                className="tab"
                aria-selected={tab.active}
                aria-current={tab.active ? "true" : "false"}
                title={tab.url ? `Switch to ${tab.title || tab.url}` : "Switch tab"}
                onClick={() => {
                  if (!tab.active && onSwitchTab) onSwitchTab(tab.index);
                }}
              >
                <Globe size={11} aria-hidden="true" />
                <span>{tab.title || tab.url || "Untitled"}</span>
              </button>
            ))}
          </div>
        ) : null}

        {frame ? (
          <Screen
            frame={frame}
            target={target}
            takeoverEnabled={takeoverEnabled && !timeTravelStep}
            blockedHint={timeTravelStep ? "This is a saved snapshot of an earlier step. Exit time travel to use the live page." : blockedHint}
            pinMode={Boolean(pinMode && !timeTravelStep)}
            pinnedPoint={!timeTravelStep ? pinnedPoint : null}
            onPinPoint={onPinPoint}
            onClick={onClick}
            onScroll={onScroll}
          />
        ) : (
          <div className="placeholder">
            <div className="placeholder-card">
              <div className="placeholder-icon" aria-hidden="true">
                <Monitor size={24} />
              </div>
              <p className="placeholder-title">Live browser view</p>
              <p className="placeholder-sub">
                The page stream will appear here full-screen as soon as the agent opens a site.
              </p>
            </div>
          </div>
        )}

        {takeoverEnabled && !timeTravelStep ? (
          <TakeoverBar
            onType={onType}
            onScroll={onScroll}
            onSaveSession={onSaveSession}
            hasSavedSession={hasSavedSession}
          />
        ) : null}
      </div>
    </section>
  );
}

interface ScreenProps {
  frame: Frame;
  target: BrowserTarget | null;
  takeoverEnabled: boolean;
  blockedHint?: string;
  pinMode?: boolean;
  pinnedPoint?: { x: number; y: number } | null;
  onPinPoint?: (pt: { x: number; y: number } | null) => void;
  onClick: (x: number, y: number) => void;
  onScroll: (dy: number) => void;
}

function Screen({
  frame,
  target,
  takeoverEnabled,
  blockedHint,
  pinMode,
  pinnedPoint,
  onPinPoint,
  onClick,
  onScroll,
}: ScreenProps) {
  const lastWheelRef = useRef(0);
  const wheelDeltaRef = useRef(0);
  const [hintVisible, setHintVisible] = useState(false);
  const hintTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // A wheel or click that cannot reach the page says why instead of doing nothing.
  const showBlockedHint = () => {
    if (!blockedHint) return;
    setHintVisible(true);
    if (hintTimerRef.current) clearTimeout(hintTimerRef.current);
    hintTimerRef.current = setTimeout(() => setHintVisible(false), HINT_MS);
  };

  const handleClick = (event: MouseEvent<HTMLImageElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    if (bounds.width === 0 || bounds.height === 0) return;
    // Convert displayed pixels to frame pixel space.
    const x = Math.round(((event.clientX - bounds.left) / bounds.width) * frame.w);
    const y = Math.round(((event.clientY - bounds.top) / bounds.height) * frame.h);
    if ((pinMode || event.altKey) && onPinPoint) {
      onPinPoint({ x, y });
      return;
    }
    if (!takeoverEnabled) {
      showBlockedHint();
      return;
    }
    onClick(x, y);
  };

  const handleWheel = (event: WheelEvent<HTMLImageElement>) => {
    if (!takeoverEnabled) {
      showBlockedHint();
      return;
    }
    wheelDeltaRef.current += event.deltaY;
    const now = Date.now();
    if (now - lastWheelRef.current < 160) return;
    const dy = Math.round(wheelDeltaRef.current);
    if (Math.abs(dy) < 25) return;
    lastWheelRef.current = now;
    wheelDeltaRef.current = 0;
    onScroll(Math.max(-900, Math.min(900, dy)));
  };

  const rect = target?.rect;
  const overlay =
    rect && frame.w > 0 && frame.h > 0
      ? {
          left: `${(rect.x / frame.w) * 100}%`,
          top: `${(rect.y / frame.h) * 100}%`,
          width: `${(rect.w / frame.w) * 100}%`,
          height: `${(rect.h / frame.h) * 100}%`,
        }
      : null;
  const labelBelow = Boolean(rect && rect.y < 36);
  const pinStyle =
    pinnedPoint && frame.w > 0 && frame.h > 0
      ? {
          left: `${(pinnedPoint.x / frame.w) * 100}%`,
          top: `${(pinnedPoint.y / frame.h) * 100}%`,
        }
      : null;

  return (
    <div className="viewport">
      <div className="viewport-inner">
        {/* eslint-disable-next-line @next/next/no-img-element -- live frames are data URIs; next/image cannot optimise them */}
        <img
          className={`page-shot${takeoverEnabled || pinMode ? " is-takeover" : ""}`}
          src={`data:image/jpeg;base64,${frame.image}`}
          alt={`Screenshot of ${frame.title || frame.url || "the current page"}`}
          width={frame.w}
          height={frame.h}
          draggable={false}
          onClick={handleClick}
          onWheel={handleWheel}
          title={
            pinMode
              ? "Click any element to pin it to your next guidance message"
              : takeoverEnabled
                ? "Click anywhere on the page or scroll with your mouse wheel / trackpad (Alt+click to pin)"
                : "Alt+click any element to pin it to your guidance"
          }
        />
        {hintVisible && blockedHint ? (
          <div className="viewport-hint" role="status">
            {blockedHint}
          </div>
        ) : null}
        {overlay && target ? (
          <div
            className={`target-box${target.risky ? " is-risky" : ""}${target.recent ? " is-recent" : ""}`}
            style={overlay}
          >
            <span className={`target-label${labelBelow ? " is-below" : ""}`}>{target.action}</span>
            <span className="target-cursor" aria-hidden="true">
              <span className="target-ripple" />
              <svg
                className="target-pointer"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="currentColor"
                stroke="#fff"
                strokeWidth="2"
              >
                <path d="M5.5 3.21V20.8c0 .45.54.67.85.35l4.86-4.86a.5.5 0 0 1 .35-.15h6.87a.5.5 0 0 0 .35-.85L6.35 2.86a.5.5 0 0 0-.85.35Z" />
              </svg>
            </span>
          </div>
        ) : null}
        {pinStyle && pinnedPoint ? (
          <div className="pin-marker" style={pinStyle}>
            <span className="pin-pulse" aria-hidden="true" />
            <span className="pin-badge">
              <Crosshair size={11} aria-hidden="true" />
              <span>
                Pinned ({pinnedPoint.x}, {pinnedPoint.y})
              </span>
              {onPinPoint ? (
                <button
                  type="button"
                  className="pin-clear"
                  onClick={(e) => {
                    e.stopPropagation();
                    onPinPoint(null);
                  }}
                  title="Remove pin"
                >
                  <X size={10} />
                </button>
              ) : null}
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function TakeoverBar({
  onType,
  onScroll,
  onSaveSession,
  hasSavedSession,
}: {
  onType: (text: string, pressEnter: boolean) => void;
  onScroll: (dy: number) => void;
  onSaveSession?: () => void;
  hasSavedSession?: boolean;
}) {
  const [text, setText] = useState("");
  const [pressEnter, setPressEnter] = useState(false);

  const submit = () => {
    if (text.length === 0) return;
    onType(text, pressEnter);
    setText("");
  };

  return (
    <div className="takeover-bar" role="group" aria-label="Take over the browser">
      <div className="takeover-badge">
        <Hand size={14} aria-hidden="true" />
        <strong>Interactive takeover</strong>
      </div>
      <div className="takeover-input-wrap">
        <Keyboard size={14} className="takeover-input-icon" aria-hidden="true" />
        <input
          className="input takeover-input"
          aria-label="Text to type into the focused field"
          placeholder="Click a field on the page, then type here…"
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              submit();
            }
          }}
        />
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={pressEnter}
          onChange={(event) => setPressEnter(event.target.checked)}
        />
        <CornerDownLeft size={12} aria-hidden="true" />
        Enter
      </label>
      <button type="button" className="btn btn-primary btn-sm" onClick={submit} disabled={text.length === 0}>
        Type
      </button>
      <div className="takeover-scroll-group">
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => onScroll(-500)}
          aria-label="Scroll up"
          title="Scroll up"
        >
          <ArrowUp size={13} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => onScroll(500)}
          aria-label="Scroll down"
          title="Scroll down"
        >
          <ArrowDown size={13} aria-hidden="true" />
        </button>
      </div>
      {onSaveSession ? (
        <button
          type="button"
          className="btn btn-sm"
          onClick={onSaveSession}
          title="Save current browser cookies and login session for future runs"
        >
          <BookmarkCheck size={13} aria-hidden="true" />
          <span>{hasSavedSession ? "Update login" : "Save login"}</span>
        </button>
      ) : null}
    </div>
  );
}
