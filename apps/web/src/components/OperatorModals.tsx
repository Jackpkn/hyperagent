"use client";

import { useState } from "react";
import { UserCheck, X } from "lucide-react";
import type { OperatorProfile } from "@/lib/operator-store";

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
