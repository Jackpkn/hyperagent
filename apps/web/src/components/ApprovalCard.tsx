"use client";

import { useState, type KeyboardEvent } from "react";
import { Check, ShieldAlert, X } from "lucide-react";
import type { Approval } from "@/lib/protocol";
import { formatCell } from "@/lib/format";

interface ApprovalCardProps {
  approval: Approval;
  onApprove: (stepId: string) => void;
  onReject: (stepId: string, reason: string) => void;
}

export function ApprovalCard({ approval, onApprove, onReject }: ApprovalCardProps) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const argEntries = Object.entries(approval.args);

  // Enter approves when the card itself has focus. Inside the reject form,
  // Enter must keep its normal behaviour.
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key === "Enter") {
      event.preventDefault();
      onApprove(approval.step_id);
    }
  };

  return (
    <section
      className="approval"
      role="group"
      aria-labelledby={`approval-${approval.step_id}`}
      tabIndex={0}
      onKeyDown={onKeyDown}
    >
      <div className="approval-head">
        <ShieldAlert size={15} className="approval-icon" aria-hidden="true" />
        <div className="approval-title" id={`approval-${approval.step_id}`}>
          Approval required before acting
        </div>
      </div>

      <div className="approval-action">{approval.action_label}</div>
      {approval.target_label ? (
        <div className="step-target-chip mono" title={approval.target_label}>
          Target: {approval.target_label}
        </div>
      ) : null}

      <p className="approval-reason">
        <strong>Why:</strong> {approval.reason}
      </p>

      {argEntries.length > 0 ? (
        <pre className="args">
          {argEntries.map(([key, value]) => `${key}: ${formatCell(value)}`).join("\n")}
        </pre>
      ) : null}

      {rejecting ? (
        <form
          className="reject-form"
          onSubmit={(event) => {
            event.preventDefault();
            onReject(approval.step_id, reason.trim());
          }}
        >
          <label className="field-label" htmlFor={`reason-${approval.step_id}`}>
            Reason for skipping (optional)
          </label>
          <input
            id={`reason-${approval.step_id}`}
            className="input"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Optional: tell the agent why, or what to do instead"
            autoFocus
          />
          <div className="approval-actions">
            <button type="submit" className="btn btn-danger btn-sm">
              <X size={13} aria-hidden="true" />
              Confirm reject
            </button>
            <button
              type="button"
              className="btn btn-quiet btn-sm"
              onClick={() => setRejecting(false)}
            >
              Back
            </button>
          </div>
        </form>
      ) : (
        <div className="approval-actions">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => onApprove(approval.step_id)}
          >
            <Check size={13} aria-hidden="true" />
            Approve
            <kbd className="approval-kbd" aria-hidden="true">
              ↵
            </kbd>
          </button>
          <button type="button" className="btn btn-sm" onClick={() => setRejecting(true)}>
            <X size={13} aria-hidden="true" />
            Reject
          </button>
        </div>
      )}
    </section>
  );
}
