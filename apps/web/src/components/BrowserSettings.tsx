"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChevronDown, Settings2 } from "lucide-react";
import type { ApprovalMode } from "@/lib/protocol";

const MODES: { value: ApprovalMode; label: string; short: string; detail: string }[] = [
  {
    value: "risky",
    label: "Ask before risky actions",
    short: "Risky actions",
    detail: "Pauses before submitting, buying, sending, or deleting.",
  },
  {
    value: "always",
    label: "Ask before every action",
    short: "Every action",
    detail: "You approve each click, typed value, and navigation.",
  },
  {
    value: "never",
    label: "Fully autonomous",
    short: "Autonomous",
    detail: "Runs to completion without asking for approval.",
  },
];

interface BrowserSettingsProps {
  mode: ApprovalMode;
  onModeChange: (mode: ApprovalMode) => void;
  startUrl: string;
  onStartUrlChange: (url: string) => void;
  persistSession: boolean;
  hasSavedSession?: boolean;
  onTogglePersistSession: () => void;
  onClearSavedSession: () => void;
}

export function BrowserSettings(props: BrowserSettingsProps) {
  const [placement, setPlacement] = useState({ above: false, height: 460 });
  const [invalidUrl, setInvalidUrl] = useState(false);
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const selected = MODES.find((option) => option.value === props.mode)!;

  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const rect = root.current?.getBoundingClientRect();
      if (!rect) return;
      const below = window.innerHeight - rect.bottom;
      const above = rect.top > below;
      setPlacement({ above, height: Math.max(80, Math.min(460, (above ? rect.top : below) - 16)) });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="browser-settings" ref={root}>
      <button ref={trigger} type="button" className="btn btn-quiet browser-settings-trigger"
        aria-expanded={open} aria-controls="browser-settings-panel" onClick={() => setOpen((value) => !value)}>
        <Settings2 size={15} aria-hidden="true" />
        <span>Browser settings <span className="hint">· {selected.short}</span></span>
        <ChevronDown size={13} aria-hidden="true" />
      </button>
      <div id="browser-settings-panel" className={`browser-settings-panel${placement.above ? " opens-above" : ""}`}
        style={{ maxHeight: placement.height }} hidden={!open}>
        <label htmlFor="start-url" className="field-label">Start at a URL (optional)</label>
        <input id="start-url" className="input" type="url" inputMode="url" pattern="https?://.*"
          placeholder="https://" autoComplete="off" value={props.startUrl}
          aria-invalid={invalidUrl || undefined} aria-describedby={invalidUrl ? "start-url-error" : undefined}
          onChange={(event) => { props.onStartUrlChange(event.target.value); setInvalidUrl(false); }}
          onInvalid={(event) => {
            event.preventDefault();
            setOpen(true);
            setInvalidUrl(true);
            const input = event.currentTarget;
            requestAnimationFrame(() => input.focus());
          }} />
        {invalidUrl ? <p className="hint" id="start-url-error" role="alert">Enter a full http:// or https:// URL.</p> : null}
        <button type="button" className="launch-nav-item settings-logins" role="switch"
          aria-checked={props.persistSession} onClick={props.onTogglePersistSession}>
          Keep logins <span className="launch-switch" aria-hidden="true" />
        </button>
        {props.hasSavedSession ? (
          <button type="button" className="btn btn-quiet btn-sm" onClick={props.onClearSavedSession}>Clear cookies</button>
        ) : null}
        <fieldset className="settings-approval">
          <legend className="field-label">Approval mode</legend>
          {MODES.map((option) => (
            <label className="settings-mode" key={option.value}>
              <input type="radio" name="approval-mode" value={option.value} checked={props.mode === option.value}
                onChange={() => props.onModeChange(option.value)} />
              <span><strong>{option.label}</strong><span className="hint">{option.detail}</span></span>
            </label>
          ))}
        </fieldset>
      </div>
    </div>
  );
}
