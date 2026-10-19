import { Database, Eye, ExternalLink, FileCheck2 } from "lucide-react";
import type { Finding, RunResult, StepRecord, Usage } from "@/lib/protocol";
import { domainOf, formatCell } from "@/lib/format";
import { ResultReport } from "./ResultReport";

interface ResultsPanelProps {
  findings: Finding[];
  result: RunResult | null;
  previousResult?: RunResult | null;
  usage?: Usage | null;
  finished: boolean;
  endedWithoutResult: string | null;
  mode?: "findings" | "result";
  goal?: string;
  steps?: StepRecord[];
  captureStepIds?: string[];
  selectedStepId?: string | null;
  onInspectStep?: (stepId: string | null) => void;
  onUseFollowUp?: (text: string) => void;
}

const PREVIEW_FIELDS = 6;

export function ResultsPanel({
  findings,
  result,
  previousResult,
  usage,
  finished,
  endedWithoutResult,
  mode = "result",
  goal,
  steps,
  captureStepIds,
  selectedStepId,
  onInspectStep,
  onUseFollowUp,
}: ResultsPanelProps) {
  if (mode === "findings") {
    return (
      <div className="panel-body">
        {findings.length === 0 ? (
          <div className="empty-state">
            <Database size={20} className="empty-icon" aria-hidden="true" />
            <p className="empty-title">No findings saved yet</p>
            <p className="empty-sub">
              {finished
                ? "The run finished without saving intermediate findings."
                : "Structured facts recorded by the agent will stream here live."}
            </p>
          </div>
        ) : (
          <ul className="findings-list" aria-label="Collected data">
            {findings.map((finding, index) => (
              <li key={`${index}-${finding.source_url}`}>
                <FindingCard
                  finding={finding}
                  index={index + 1}
                  selectedStepId={selectedStepId}
                  onInspectStep={onInspectStep}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  return (
    <div className="panel-body">
      {result ? (
        <ResultReport
          result={result}
          previousResult={previousResult}
          usage={usage}
          findings={findings}
          goal={goal}
          steps={steps}
          captureStepIds={captureStepIds}
          selectedStepId={selectedStepId}
          onInspectStep={onInspectStep}
          onUseFollowUp={onUseFollowUp}
        />
      ) : (
        <div className="empty-state">
          <FileCheck2 size={20} className="empty-icon" aria-hidden="true" />
          <p className="empty-title">
            {finished ? "No final report generated" : "Final report pending"}
          </p>
          <p className="empty-sub">
            {finished
              ? endedWithoutResult ?? "The run ended before a final report was written."
              : "Once the agent completes your goal, the verified summary, data table, and exports will appear here."}
          </p>
          {finished && findings.length > 0 ? (
            <div style={{ width: "100%", marginTop: 16, textAlign: "left" }}>
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                Partial findings ({findings.length})
              </div>
              <ul className="findings-list" aria-label="Collected data">
                {findings.map((finding, index) => (
                  <li key={`${index}-${finding.source_url}`}>
                    <FindingCard
                      finding={finding}
                      index={index + 1}
                      selectedStepId={selectedStepId}
                      onInspectStep={onInspectStep}
                    />
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

export function FindingCard({
  finding,
  index,
  selectedStepId,
  onInspectStep,
}: {
  finding: Finding;
  index: number;
  selectedStepId?: string | null;
  onInspectStep?: (stepId: string | null) => void;
}) {
  const entries = Object.entries(finding.data).slice(0, PREVIEW_FIELDS);
  const hidden = Object.keys(finding.data).length - entries.length;
  const isWeb = /^https?:\/\//i.test(finding.source_url);
  const unverifiedSet = new Set(finding.unverified ?? []);
  const suspectCount = unverifiedSet.size;
  const isReceiptActive = Boolean(finding.step_id && selectedStepId === finding.step_id);

  return (
    <article className="finding">
      <div className="finding-head">
        <span className="finding-index">#{index}</span>
        {suspectCount > 0 ? (
          <span
            className="verify-badge is-suspect"
            title={`Unverified in page text: ${Array.from(unverifiedSet).join(", ")}`}
          >
            ⚠ Unverified ({suspectCount})
          </span>
        ) : (
          <span
            className="verify-badge is-verified"
            title="All extracted fields were verified against the observed page text"
          >
            ✓ Grounded
          </span>
        )}
        {finding.step_id && onInspectStep ? (
          <button
            type="button"
            className={`step-inspect-btn${isReceiptActive ? " is-active" : ""}`}
            onClick={() => onInspectStep(isReceiptActive ? null : finding.step_id!)}
            title={`Click to view the exact browser screenshot (Step #${finding.step_n ?? finding.step_id}) where this finding was captured`}
          >
            <Eye size={10} aria-hidden="true" />
            <span>{isReceiptActive ? "Viewing" : `Receipt #${finding.step_n ?? ""}`}</span>
          </button>
        ) : null}
        {isWeb ? (
          <a
            href={finding.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="finding-source"
            title={finding.source_url}
          >
            <span>{domainOf(finding.source_url)}</span>
            <ExternalLink size={11} aria-hidden="true" />
          </a>
        ) : (
          <span className="finding-source" title={finding.source_url}>
            {domainOf(finding.source_url)}
          </span>
        )}
      </div>
      <dl>
        {entries.map(([key, value]) => {
          const isSuspect = unverifiedSet.has(key);
          return (
            <div key={key} style={{ display: "contents" }}>
              <dt>{key}</dt>
              <dd className={isSuspect ? "is-suspect-val" : undefined}>
                {formatCell(value)}
                {isSuspect ? (
                  <span
                    className="suspect-inline"
                    title="Value did not appear verbatim in the observed page text"
                  >
                    ⚠ unverified
                  </span>
                ) : null}
              </dd>
            </div>
          );
        })}
      </dl>
      {hidden > 0 ? (
        <p className="hint" style={{ marginTop: 6 }}>
          +{hidden} more {hidden === 1 ? "field" : "fields"}
        </p>
      ) : null}
    </article>
  );
}
