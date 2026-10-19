"use client";

import { useState } from "react";
import {
  AlertTriangle,
  Brain,
  Check,
  CheckCircle2,
  Copy,
  ExternalLink,
  FileJson,
  FileSpreadsheet,
  GitCompare,
  Zap,
} from "lucide-react";
import type { Finding, RunResult, StepRecord, Usage } from "@/lib/protocol";
import { copyText, downloadText, resultToCsv, resultToMarkdown } from "@/lib/export";
import { domainOf, formatCell, formatCost } from "@/lib/format";
import { fastUsage, usageCost } from "@/lib/usage";
import { DataTable } from "./DataTable";
import { Markdown } from "./Markdown";
import { AnswerCard, Assumptions, Checklist, FollowUps, RunRecap } from "./ResultExtras";

interface ResultReportProps {
  result: RunResult;
  previousResult?: RunResult | null;
  usage?: Usage | null;
  /** System 1 model when Jev is configured, so a run that never delegated says so instead of staying silent. */
  fastModel?: string | null;
  findings?: Finding[];
  goal?: string;
  steps?: StepRecord[];
  captureStepIds?: string[];
  selectedStepId?: string | null;
  onInspectStep?: (stepId: string | null) => void;
  /** Pre-fills the message box with a suggested follow-up; never starts a run by itself. */
  onUseFollowUp?: (text: string) => void;
}

function isWebUrl(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

function stamp(): string {
  return new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
}

export function ResultReport({
  result,
  previousResult,
  usage,
  fastModel,
  findings,
  goal,
  steps,
  captureStepIds,
  selectedStepId,
  onInspectStep,
  onUseFollowUp,
}: ResultReportProps) {
  const [copied, setCopied] = useState<"idle" | "copied" | "failed">("idle");
  const [showDiff, setShowDiff] = useState(false);
  const hasTable = result.columns.length > 0 && result.rows.length > 0;
  const canDiff = Boolean(hasTable && previousResult && previousResult.rows.length > 0);
  const accounting = result.accounting ?? usage?.accounting;
  const cost = usageCost(usage, accounting);
  const fast = fastUsage(usage, accounting);
  const fastCalls = fast.calls;
  const unverifiedValues = new Set<string>();
  for (const f of findings ?? []) {
    for (const k of f.unverified ?? []) {
      const val = formatCell(f.data[k]).trim();
      if (val) unverifiedValues.add(val.toLowerCase());
    }
  }
  // Flags that reach the delivered answer, so the banner never claims "verified" over a flagged value.
  const flaggedInResult = new Set(
    result.rows.flatMap((row) =>
      result.columns
        .map((c) => formatCell(row[c]).trim().toLowerCase())
        .filter((v) => v && unverifiedValues.has(v)),
    ),
  ).size;
  const checklist = result.checklist ?? [];
  const assumptions = result.assumptions ?? [];
  const followUps = result.follow_ups ?? [];
  const remembered = result.remember ?? [];
  const singleAnswer = hasTable && result.rows.length === 1 && result.columns.length <= 8;
  const verdictSub = verdictText(result.success, checklist.length, flaggedInResult);

  const onCopy = async () => {
    const ok = await copyText(resultToMarkdown(result));
    setCopied(ok ? "copied" : "failed");
    setTimeout(() => setCopied("idle"), 2000);
  };

  return (
    <article className="result-report" aria-label="Final report">
      <div className="verdict-banner" data-tone={result.success ? "ok" : "wait"}>
        <div className="verdict-main">
          {result.success ? (
            <CheckCircle2 size={16} className="verdict-icon" aria-hidden="true" />
          ) : (
            <AlertTriangle size={16} className="verdict-icon" aria-hidden="true" />
          )}
          <div>
            <strong className="verdict-title">
              {result.success ? "Goal Completed" : "Partial Result"}
            </strong>
            <span className="verdict-sub">{verdictSub}</span>
          </div>
        </div>

        <div className="result-actions-inline" role="group" aria-label="Export the result">
          <button type="button" className="btn btn-sm" onClick={onCopy} title="Copy report as Markdown">
            {copied === "copied" ? <Check size={13} /> : <Copy size={13} />}
            {copied === "copied" ? "Copied" : copied === "failed" ? "Failed" : "Copy MD"}
          </button>
          {hasTable ? (
            <button
              type="button"
              className="btn btn-sm"
              onClick={() =>
                downloadText(`hyperagent-${stamp()}.csv`, resultToCsv(result), "text/csv")
              }
              title="Download table as CSV"
            >
              <FileSpreadsheet size={13} />
              CSV
            </button>
          ) : null}
          <button
            type="button"
            className="btn btn-sm"
            onClick={() =>
              downloadText(
                `hyperagent-audit-${stamp()}.json`,
                JSON.stringify(
                  {
                    exported_at: new Date().toISOString(),
                    goal: goal ?? "",
                    usage: usage ?? null,
                    result,
                    findings: findings ?? [],
                    audit_steps: (steps ?? []).map((s) => ({
                      id: s.id,
                      n: s.n,
                      status: s.status,
                      system: s.system,
                      url: s.url,
                      action: s.action,
                      thought: s.thought,
                      result: s.result,
                      error: s.error,
                      started_at: s.started_at,
                      ended_at: s.ended_at,
                    })),
                  },
                  null,
                  2,
                ),
                "application/json",
              )
            }
            title="Download complete verified audit trail (goal, steps, findings, and result)"
          >
            <FileJson size={13} />
            Audit JSON
          </button>
        </div>
      </div>

      {usage || accounting ? (
        <div className="efficiency-strip" aria-label="Model usage and cost">
          {accounting ? (
            <span className="efficiency-item">
              <strong>Model calls:</strong> {accounting.by_purpose.planner.attempts} planner
              {` · ${accounting.by_purpose.extract.attempts} extraction · ${accounting.by_purpose.text.attempts} text`}
              {` · ${(accounting.summary.input_tokens + accounting.summary.output_tokens).toLocaleString()} recorded tok`}
              {accounting.summary.unknown_usage_count > 0 ? " (partial usage)" : ""}
              {accounting.summary.cache_read_tokens > 0
                ? ` (${accounting.summary.cache_read_tokens.toLocaleString()} cached)` : ""}
              <span title={cost.description}>
                {` · ${cost.label}: ${formatCost(cost.amount ?? 0)}`}
              </span>
            </span>
          ) : usage ? (
            <span className="efficiency-item" title={cost.description}>
              <strong>Planner + extraction:</strong> {usage.llm_calls} planner calls
              {usage.extract_calls ? ` · ${usage.extract_calls} extractions` : ""}
              {` · ${(usage.input_tokens + usage.output_tokens).toLocaleString()} recorded tok`}
              {usage.cached_input_tokens ? ` (${usage.cached_input_tokens.toLocaleString()} cached)` : ""}
              {` · Legacy subtotal: ${formatCost(usage.cost_usd)}`}
            </span>
          ) : null}
          {fastCalls > 0 ? (
            <span className="efficiency-item efficiency-highlight">
              <Zap size={12} aria-hidden="true" />
              <strong>Jev (System 1):</strong> {fastCalls} {fastCalls === 1 ? "call" : "calls"}
              {` (${fast.avgMs}ms avg)`}
              {fast.actions !== undefined ? ` · ${fast.actions} completed actions` : ""}
              {" · no screenshots"}
            </span>
          ) : fastModel ? (
            <span className="efficiency-item" title="The planner can delegate focused on-page UI work to Jev">
              <Zap size={12} aria-hidden="true" />
              <strong>Jev (System 1):</strong> not used. The planner did every action itself.
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="result-summary-card">
        <div className="result-summary">
          <Markdown source={result.summary} />
        </div>
      </div>

      {steps && steps.length > 0 ? <RunRecap steps={steps} /> : null}

      {checklist.length > 0 ? (
        <Checklist items={checklist} selectedStepId={selectedStepId} onInspectStep={onInspectStep} />
      ) : null}

      {singleAnswer ? (
        <AnswerCard
          columns={result.columns}
          row={result.rows[0]}
          unverifiedValues={unverifiedValues}
          findings={findings}
          steps={steps}
          captureStepIds={captureStepIds}
          selectedStepId={selectedStepId}
          onInspectStep={onInspectStep}
        />
      ) : hasTable ? (
        <div className="result-section">
          <div className="result-section-head">
            <h3 className="section-label eyebrow">
              Structured Data · {result.rows.length} {result.rows.length === 1 ? "row" : "rows"}
            </h3>
            {canDiff ? (
              <button
                type="button"
                className={`btn btn-sm${showDiff ? " btn-primary" : ""}`}
                onClick={() => setShowDiff((prev) => !prev)}
                title="Compare cell values and rows against the previous run in history"
              >
                <GitCompare size={12} aria-hidden="true" />
                <span>{showDiff ? "Showing diff vs previous run" : "Diff vs previous run"}</span>
              </button>
            ) : null}
          </div>
          <DataTable
            columns={result.columns}
            rows={result.rows}
            compareRows={showDiff && previousResult ? previousResult.rows : undefined}
            unverifiedValues={unverifiedValues}
            findings={findings}
            steps={steps}
            captureStepIds={captureStepIds}
            selectedStepId={selectedStepId}
            onInspectStep={onInspectStep}
          />
        </div>
      ) : null}

      {result.issues.length > 0 ? (
        <div className="result-section">
          <h3 className="section-label eyebrow">Open Issues & Caveats</h3>
          <ul className="issues">
            {result.issues.map((issue, index) => (
              <li key={index}>{issue}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {assumptions.length > 0 ? <Assumptions items={assumptions} /> : null}

      {remembered.length > 0 ? (
        <div className="result-section">
          <h3 className="section-label eyebrow">Saved to memory</h3>
          <ul className="issues assumptions">
            {remembered.map((item) => (
              <li key={item}>
                <Brain size={12} aria-hidden="true" /> {item}
              </li>
            ))}
          </ul>
          <p className="memory-hint">Applied in your future chats. Edit or remove it under Memory.</p>
        </div>
      ) : null}

      {result.sources.length > 0 ? (
        <div className="result-section">
          <h3 className="section-label eyebrow">Verified Sources ({result.sources.length})</h3>
          <ul className="sources">
            {result.sources.map((source, index) => (
              <li key={`${index}-${source.url}`} className="source-item">
                {isWebUrl(source.url) ? (
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="source-link"
                  >
                    <span className="source-title">{source.title || domainOf(source.url)}</span>
                    <span className="source-domain mono">
                      {domainOf(source.url)}
                      <ExternalLink size={11} aria-hidden="true" />
                    </span>
                  </a>
                ) : (
                  <div className="source-link">
                    <span className="source-title">{source.title || source.url}</span>
                    <span className="source-domain mono">{domainOf(source.url)}</span>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {followUps.length > 0 && onUseFollowUp ? <FollowUps items={followUps} onUse={onUseFollowUp} /> : null}
    </article>
  );
}

function verdictText(success: boolean, checklistCount: number, flagged: number): string {
  if (!success) return "Not everything was done — see the checklist and open issues below.";
  if (flagged > 0) {
    return `Done, but ${flagged} ${flagged === 1 ? "value" : "values"} couldn't be matched to the page text — marked ⚠ below.`;
  }
  if (checklistCount > 0) {
    return `All ${checklistCount} ${checklistCount === 1 ? "requirement" : "requirements"} met, each with evidence below.`;
  }
  return "The agent reports every requested item was found.";
}
