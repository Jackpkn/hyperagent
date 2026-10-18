"use client";

import { useState } from "react";
import {
  CheckCircle2,
  Clock,
  FileText,
  History,
  Play,
  Trash2,
  UserCheck,
  X,
} from "lucide-react";
import type { OperatorProfile, RunHistoryEntry } from "@/lib/operator-store";
import { formatCost, formatDuration } from "@/lib/format";

interface ProfileModalProps {
  profile: OperatorProfile;
  onSave: (profile: OperatorProfile) => void;
  onClose: () => void;
}

export function ProfileModal({ profile, onSave, onClose }: ProfileModalProps) {
  const [draft, setDraft] = useState<OperatorProfile>(profile);

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    onSave(draft);
    onClose();
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="profile-modal-title">
      <div className="modal-card">
        <div className="modal-head">
          <div className="modal-title-group">
            <UserCheck size={16} className="modal-icon" aria-hidden="true" />
            <h2 id="profile-modal-title" className="modal-title">
              Autofill &amp; Operator Context
            </h2>
          </div>
          <button
            type="button"
            className="btn btn-quiet btn-sm"
            onClick={onClose}
            aria-label="Close modal"
          >
            <X size={15} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-body">
          <p className="modal-desc">
            Store reusable non-sensitive details once so the agent can fill forms (name,
            email, address, preferences) automatically without re-typing them in every prompt. Never
            enter passwords or card numbers here.
          </p>

          <label className="profile-toggle-row">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
            />
            <span>Include this profile context automatically when starting tasks</span>
          </label>

          <div className="profile-grid">
            <div className="profile-field">
              <label htmlFor="prof-name">Full Name</label>
              <input
                id="prof-name"
                className="input"
                placeholder="e.g. Alex Rivera"
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
            </div>

            <div className="profile-field">
              <label htmlFor="prof-email">Email</label>
              <input
                id="prof-email"
                type="email"
                className="input"
                placeholder="e.g. alex@example.com"
                value={draft.email}
                onChange={(e) => setDraft({ ...draft, email: e.target.value })}
              />
            </div>

            <div className="profile-field">
              <label htmlFor="prof-phone">Phone</label>
              <input
                id="prof-phone"
                className="input"
                placeholder="e.g. +1 555-0199"
                value={draft.phone}
                onChange={(e) => setDraft({ ...draft, phone: e.target.value })}
              />
            </div>

            <div className="profile-field">
              <label htmlFor="prof-company">Company / Role</label>
              <input
                id="prof-company"
                className="input"
                placeholder="e.g. Acme Corp · Product Engineer"
                value={draft.company}
                onChange={(e) => setDraft({ ...draft, company: e.target.value })}
              />
            </div>

            <div className="profile-field profile-field-full">
              <label htmlFor="prof-address">Address / City / State / Zip</label>
              <input
                id="prof-address"
                className="input"
                placeholder="e.g. 123 Main St, Boston, MA 02101"
                value={draft.address}
                onChange={(e) => setDraft({ ...draft, address: e.target.value })}
              />
            </div>

            <div className="profile-field profile-field-full">
              <label htmlFor="prof-notes">Custom Preferences / Instructions</label>
              <textarea
                id="prof-notes"
                className="input profile-textarea"
                rows={2}
                placeholder="e.g. Prefer direct flights, morning departures, USD currency"
                value={draft.notes}
                onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
              />
            </div>
          </div>

          <div className="modal-foot">
            <button
              type="button"
              className="btn btn-quiet btn-sm"
              onClick={() =>
                setDraft({
                  enabled: true,
                  name: "",
                  email: "",
                  phone: "",
                  address: "",
                  company: "",
                  notes: "",
                })
              }
            >
              Clear fields
            </button>
            <div className="modal-foot-right">
              <button type="button" className="btn btn-sm" onClick={onClose}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary btn-sm">
                Save profile
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}

interface HistoryModalProps {
  entries: RunHistoryEntry[];
  onView: (entry: RunHistoryEntry) => void;
  onRerun: (goal: string) => void;
  onDelete: (id: string) => void;
  onClearAll: () => void;
  onClose: () => void;
}

export function HistoryModal({
  entries,
  onView,
  onRerun,
  onDelete,
  onClearAll,
  onClose,
}: HistoryModalProps) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="history-modal-title">
      <div className="modal-card modal-card-wide">
        <div className="modal-head">
          <div className="modal-title-group">
            <History size={16} className="modal-icon" aria-hidden="true" />
            <h2 id="history-modal-title" className="modal-title">
              Recent Runs ({entries.length})
            </h2>
          </div>
          <div className="modal-head-actions">
            {entries.length > 0 ? (
              <button
                type="button"
                className="btn btn-quiet btn-sm"
                onClick={onClearAll}
                title="Clear all saved run history"
              >
                <Trash2 size={13} aria-hidden="true" />
                <span>Clear all</span>
              </button>
            ) : null}
            <button
              type="button"
              className="btn btn-quiet btn-sm"
              onClick={onClose}
              aria-label="Close modal"
            >
              <X size={15} />
            </button>
          </div>
        </div>

        <div className="modal-body">
          {entries.length === 0 ? (
            <div className="empty-state" style={{ padding: "28px 12px" }}>
              <History size={22} className="empty-icon" aria-hidden="true" />
              <p className="empty-title">No saved runs yet</p>
              <p className="empty-sub">
                Completed tasks and their extracted tables will automatically be saved here so you
                can revisit or re-run them anytime.
              </p>
            </div>
          ) : (
            <ul className="history-list">
              {entries.map((item) => {
                const isSuccess = item.result?.success ?? item.status === "done";
                const dateStr = new Date(item.createdAt).toLocaleString(undefined, {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                });
                return (
                  <li key={item.id} className="history-item">
                    <div className="history-item-main">
                      <div className="history-item-top">
                        <span
                          className={`pill ${isSuccess ? "" : ""}`}
                          data-tone={isSuccess ? "ok" : "wait"}
                        >
                          <CheckCircle2 size={11} aria-hidden="true" />
                          {isSuccess ? "Completed" : "Partial"}
                        </span>
                        <span className="history-date">{dateStr}</span>
                        <span className="history-metrics">
                          <Clock size={11} aria-hidden="true" />
                          {formatDuration(item.elapsedS)} · {item.stepsCount} steps ·{" "}
                          {formatCost(item.costUsd)}
                        </span>
                      </div>
                      <p className="history-goal">{item.goal}</p>
                      {item.result?.summary ? (
                        <p className="history-summary">{item.result.summary.slice(0, 180)}</p>
                      ) : null}
                    </div>
                    <div className="history-item-actions">
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => {
                          onView(item);
                          onClose();
                        }}
                        title="Open report & extracted findings"
                      >
                        <FileText size={13} aria-hidden="true" />
                        <span>Report</span>
                      </button>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={() => {
                          onRerun(item.goal);
                          onClose();
                        }}
                        title="Run this goal again in a fresh browser"
                      >
                        <Play size={12} aria-hidden="true" />
                        <span>Re-run</span>
                      </button>
                      <button
                        type="button"
                        className="btn btn-quiet btn-sm"
                        onClick={() => onDelete(item.id)}
                        aria-label="Delete from history"
                        title="Remove from history"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
