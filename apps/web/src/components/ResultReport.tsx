"use client";

import { useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Copy,
  ExternalLink,
  FileJson,
  FileSpreadsheet,
  GitCompare,
  Zap,
} from "lucide-react";
import type { Finding, RunResult, Usage } from "@/lib/protocol";
import { copyText, downloadText, resultToCsv, resultToMarkdown } from "@/lib/export";
import { domainOf, formatCell, formatCost } from "@/lib/format";
import { DataTable } from "./DataTable";
import { Markdown } from "./Markdown";

interface ResultReportProps {
  result: RunResult;
  previousResult?: RunResult | null;
  usage?: Usage | null;
  findings?: Finding[];
}

function isWebUrl(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

function stamp(): string {
  return new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
}

export function ResultReport({ result, previousResult, usage, findings }: ResultReportProps) {
  const [copied, setCopied] = useState<"idle" | "copied" | "failed">("idle");
  const [showDiff, setShowDiff] = useState(false);
  const hasTable = result.columns.length > 0 && result.rows.length > 0;
  const canDiff = Boolean(hasTable && previousResult && previousResult.rows.length > 0);
  const fastCalls = usage?.fast_calls ?? 0;
  const avgFastMs = fastCalls > 0 ? Math.round((usage?.fast_ms_total ?? 0) / fastCalls) : 0;
  const estTokensSaved = fastCalls * 4000;
  const unverifiedValues = new Set<string>();
  for (const f of findings ?? []) {
    for (const k of f.unverified ?? []) {
      const val = formatCell(f.data[k]).trim();
      if (val) unverifiedValues.add(val.toLowerCase());
    }
  }

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
            <span className="verdict-sub">
              {result.success
                ? "All requested fields and actions were verified."
                : "Some items could not be verified — see open issues below."}
            </span>
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
                `hyperagent-${stamp()}.json`,
                JSON.stringify(result, null, 2),
                "application/json",
              )
            }
            title="Download full JSON result"
          >
            <FileJson size={13} />
            JSON
          </button>
        </div>
      </div>

      {usage && (usage.llm_calls > 0 || fastCalls > 0) ? (
        <div className="efficiency-strip" aria-label="Token and dual-system efficiency">
          <span className="efficiency-item">
            <strong>Planner (System 2):</strong> {usage.llm_calls}{" "}
            {usage.llm_calls === 1 ? "turn" : "turns"}
            {usage.input_tokens + usage.output_tokens > 0
              ? ` · ${(usage.input_tokens + usage.output_tokens).toLocaleString()} tok`
              : ""}
            {usage.cost_usd > 0 ? ` · ${formatCost(usage.cost_usd)}` : ""}
          </span>
          {fastCalls > 0 ? (
            <span className="efficiency-item efficiency-highlight">
              <Zap size={12} aria-hidden="true" />
              <strong>Jev (System 1):</strong> {fastCalls}{" "}
              {fastCalls === 1 ? "action" : "actions"} ({avgFastMs}ms avg) ·{" "}
              <strong>~{estTokensSaved.toLocaleString()} tokens saved</strong> (no screenshots)
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="result-summary-card">
        <div className="result-summary">
          <Markdown source={result.summary} />
        </div>
      </div>

      {hasTable ? (
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
    </article>
  );
}
