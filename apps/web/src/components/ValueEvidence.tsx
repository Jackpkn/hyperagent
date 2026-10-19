"use client";

import { ExternalLink, Eye } from "lucide-react";
import type { Finding, StepRecord } from "@/lib/protocol";
import { formatCell } from "@/lib/format";
import { cellFindings, isUnverifiedField, sameSourcePage, webUrl } from "@/lib/findings";

export interface EvidenceContext {
  findings?: Finding[];
  steps?: StepRecord[];
  captureStepIds?: string[];
  selectedStepId?: string | null;
  onInspectStep?: (stepId: string | null) => void;
}

export function ValueEvidence({ row, column, findings, steps, captureStepIds, selectedStepId, onInspectStep }: {
  row: Record<string, unknown>;
  column: string;
} & EvidenceContext) {
  const value = formatCell(row[column]).trim();
  if (!value) return null;
  const matches = cellFindings(row, column, findings);
  const finding = matches.length === 1 ? matches[0] : undefined;
  const step = finding?.step_id ? steps?.find((s) => s.id === finding.step_id) : undefined;
  const flagged = finding && isUnverifiedField(finding, column);
  const source = webUrl(finding?.source_url);
  const samePage = sameSourcePage(step?.url, finding?.source_url);
  const hasCapture = Boolean(step && captureStepIds?.includes(step.id));
  const canInspect = Boolean(step?.status === "ok" && samePage && hasCapture && onInspectStep);
  const active = Boolean(step && selectedStepId === step.id);
  const timestamp = step?.ended_at ?? step?.started_at;
  const date = timestamp && Number.isFinite(timestamp) ? new Date(timestamp * 1000) : null;
  const validDate = date && Number.isFinite(date.getTime()) ? date : null;

  return (
    <details className="value-evidence">
      <summary aria-label={`Evidence for ${column}: ${value}`}>
        <Eye size={12} aria-hidden="true" />
        {matches.length > 1 ? "Ambiguous evidence" : finding ? "Evidence" : "No linked evidence"}
      </summary>
      <div className="value-evidence-body">
        {!matches.length ? <p>No matching saved finding for this value.</p> : !finding ? (
          <p>Multiple saved findings match; no single source has been selected.</p>
        ) : (
          <>
            <p><strong>{column}:</strong> {value}</p>
            <p>{flagged ? "This field was flagged as unverified when saved."
              : "Matches a saved finding. This link does not independently verify the source's claim."}</p>
            {source ? (
              <a href={source} target="_blank" rel="noopener noreferrer" className="value-evidence-source">
                {finding.source_url}<ExternalLink size={11} aria-hidden="true" />
              </a>
            ) : <p>No valid source URL was saved.</p>}
            {step ? (
              <>
                <p>Step {step.n}: {step.action?.label ?? "Recorded finding"}</p>
                {validDate ? <p>Recorded at <time dateTime={validDate.toISOString()}>
                  {validDate.toLocaleString()}
                </time></p> : <p>Recording time unavailable.</p>}
                {step.status !== "ok" ? <p>The recording step did not complete successfully.</p>
                  : !samePage ? <p>This step&apos;s browser page differs from the finding&apos;s source; its capture is not source evidence.</p>
                  : !hasCapture ? <p>No saved capture is available for this step.</p> : (
                    <p>The capture shows the browser around this step; the value may be outside the viewport.</p>
                  )}
                {canInspect ? (
                  <button type="button" className={`step-inspect-btn${active ? " is-active" : ""}`}
                    onClick={() => onInspectStep?.(active ? null : step.id)}>
                    <Eye size={12} aria-hidden="true" />{active ? "Back to live" : "View step capture"}
                  </button>
                ) : null}
              </>
            ) : <p>No recording step or capture is available.</p>}
          </>
        )}
      </div>
    </details>
  );
}
