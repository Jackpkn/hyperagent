"use client";

import { ArrowRight, Check, Eye, Lightbulb, Route, X, Zap } from "lucide-react";
import type { ChecklistItem, StepRecord } from "@/lib/protocol";
import { formatCell, formatDuration } from "@/lib/format";
import { ValueEvidence, type EvidenceContext } from "./ValueEvidence";

// Steps that hand control around rather than act on the page.
const NOT_ACTIONS = new Set(["done", "delegate", "subgoal_done", "stuck", "unsure"]);
// A step's url is the page it started on; for these that is the page being left, e.g. the blank start page.
const LEAVES_PAGE = new Set(["navigate", "search"]);
const MAX_PATH_PAGES = 4;

interface StepLinkProps {
  stepId?: string;
  stepN?: number;
  selectedStepId?: string | null;
  onInspectStep?: (stepId: string | null) => void;
}

function StepLink({ stepId, stepN, selectedStepId, onInspectStep }: StepLinkProps) {
  if (!stepId || !onInspectStep) return null;
  const active = selectedStepId === stepId;
  return (
    <button
      type="button"
      className={`step-inspect-btn${active ? " is-active" : ""}`}
      onClick={() => onInspectStep(active ? null : stepId)}
      title="Show the browser snapshot from the step where this was seen"
    >
      <Eye size={10} aria-hidden="true" />
      <span>{stepN !== undefined ? `Step ${stepN}` : "Proof"}</span>
    </button>
  );
}

/** A readable name for a visited page: the host for a site root, else its last meaningful path segment. */
function pageName(url: string): string {
  try {
    const { hostname, pathname } = new URL(url);
    const segments = pathname.split("/").filter((s) => s && !/^index\.\w+$/i.test(s));
    const last = segments[segments.length - 1];
    if (!last) return hostname.replace(/^www\./, "");
    const words = decodeURIComponent(last)
      .replace(/\.\w+$/, "")
      .replace(/_\d+$/, "") // a trailing "_657" is an id; "page-2" is a real name
      .replace(/[-_+]+/g, " ")
      .trim();
    return words.length > 32 ? `${words.slice(0, 31)}…` : words || hostname;
  } catch {
    return url;
  }
}

export function RunRecap({ steps }: { steps: StepRecord[] }) {
  const ordered = [...steps].sort((a, b) => a.n - b.n);
  const actions = ordered.filter(
    (s) => s.status === "ok" && s.action && !NOT_ACTIONS.has(s.action.name),
  );
  if (ordered.length === 0) return null;
  const jevActions = actions.filter((s) => s.system === "fast").length;
  const start = Math.min(...ordered.map((s) => s.started_at));
  const end = Math.max(...ordered.map((s) => s.ended_at ?? s.started_at));

  // The path follows the tab the agent drove; the count also includes pages read in background tabs.
  const pages: string[] = [];
  const visited = new Set<string>();
  for (const s of ordered) {
    const background = s.action?.args?.urls;
    const own = LEAVES_PAGE.has(s.action?.name ?? "") ? [] : [s.url];
    for (const url of [...own, ...(Array.isArray(background) ? background : [])]) {
      if (typeof url === "string" && /^https?:\/\//i.test(url)) visited.add(url.split("#")[0].replace(/\/$/, ""));
    }
    if (!s.url || !/^https?:\/\//i.test(s.url) || LEAVES_PAGE.has(s.action?.name ?? "")) continue;
    const name = pageName(s.url.split("#")[0]);
    if (pages[pages.length - 1] !== name) pages.push(name);
  }
  const shown =
    pages.length > MAX_PATH_PAGES ? [pages[0], "…", ...pages.slice(-(MAX_PATH_PAGES - 1))] : pages;

  return (
    <div className="run-recap" aria-label="How the agent got here">
      {shown.length > 0 ? (
        <div className="run-recap-path">
          <Route size={12} aria-hidden="true" />
          {shown.map((name, i) => (
            <span key={`${i}-${name}`} className="run-recap-page">
              {i > 0 ? <span className="run-recap-sep" aria-hidden="true">→</span> : null}
              {name}
            </span>
          ))}
        </div>
      ) : null}
      <div className="run-recap-stats">
        {actions.length} {actions.length === 1 ? "action" : "actions"}
        {jevActions > 0 ? (
          <span className="run-recap-jev">
            {" · "}
            <Zap size={11} aria-hidden="true" /> {jevActions} by Jev
          </span>
        ) : null}
        {end > start ? ` · ${formatDuration(end - start)}` : ""}
        {visited.size > 0 ? ` · ${visited.size} ${visited.size === 1 ? "page" : "pages"}` : ""}
      </div>
    </div>
  );
}

interface ChecklistProps {
  items: ChecklistItem[];
  selectedStepId?: string | null;
  onInspectStep?: (stepId: string | null) => void;
}

export function Checklist({ items, selectedStepId, onInspectStep }: ChecklistProps) {
  const met = items.filter((item) => item.met).length;
  return (
    <div className="result-section">
      <h3 className="section-label eyebrow">
        What you asked for · {met}/{items.length} met
      </h3>
      <ul className="checklist" aria-label="Requirements checklist">
        {items.map((item, index) => (
          <li key={`${index}-${item.requirement}`} className="checklist-item" data-met={item.met}>
            <span className="checklist-mark" aria-hidden="true">
              {item.met ? <Check size={12} /> : <X size={12} />}
            </span>
            <div className="checklist-body">
              <span className="checklist-req">
                {item.requirement}
                <span className="sr-only">{item.met ? " (met)" : " (not met)"}</span>
              </span>
              {item.evidence ? <span className="checklist-evidence">{item.evidence}</span> : null}
            </div>
            <StepLink
              stepId={item.step_id}
              stepN={item.step_n}
              selectedStepId={selectedStepId}
              onInspectStep={onInspectStep}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}

interface AnswerCardProps extends EvidenceContext {
  columns: string[];
  row: Record<string, unknown>;
  unverifiedValues: Set<string>;
}

/** A single-item result reads better as labelled facts than as a one-row table. */
export function AnswerCard({
  columns,
  row,
  unverifiedValues,
  findings,
  steps,
  captureStepIds,
  selectedStepId,
  onInspectStep,
}: AnswerCardProps) {
  return (
    <div className="result-section">
      <div className="result-section-head">
        <h3 className="section-label eyebrow">Answer</h3>
      </div>
      <dl className="answer-card">
        {columns.map((column) => {
          const value = formatCell(row[column]).trim();
          const flagged = Boolean(value) && unverifiedValues.has(value.toLowerCase());
          return (
            <div key={column} className="answer-fact" data-flagged={flagged}>
              <dt>{column.replace(/_/g, " ")}</dt>
              <dd>
                {value || <span className="answer-missing">not found</span>}
                {flagged ? (
                  <span className="suspect-inline" title="Value was not found verbatim in observed page text">
                    ⚠ unverified
                  </span>
                ) : null}
                <ValueEvidence row={row} column={column} findings={findings} steps={steps}
                  captureStepIds={captureStepIds} selectedStepId={selectedStepId} onInspectStep={onInspectStep} />
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}

export function Assumptions({ items }: { items: string[] }) {
  return (
    <div className="result-section">
      <h3 className="section-label eyebrow">Assumptions I made</h3>
      <ul className="issues assumptions">
        {items.map((item, index) => (
          <li key={index}>
            <Lightbulb size={12} aria-hidden="true" /> {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

interface FollowUpsProps {
  items: string[];
  onUse: (text: string) => void;
}

export function FollowUps({ items, onUse }: FollowUpsProps) {
  return (
    <div className="result-section">
      <h3 className="section-label eyebrow">Suggested next steps</h3>
      <div className="follow-ups">
        {items.map((item) => (
          <button
            key={item}
            type="button"
            className="follow-up-chip"
            onClick={() => onUse(item)}
            title="Put this in the message box so you can edit it before running"
          >
            <span>{item}</span>
            <ArrowRight size={12} aria-hidden="true" />
          </button>
        ))}
      </div>
    </div>
  );
}
