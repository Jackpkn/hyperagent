"use client";

import { useId, useState } from "react";
import { Check, HelpCircle } from "lucide-react";

export function InlineQuestion({ question, answer, pending = false, onAnswer }: {
  question: string;
  answer?: string;
  pending?: boolean;
  onAnswer?: (text: string) => boolean;
}) {
  const id = useId();
  const [draft, setDraft] = useState("");
  return (
    <section className="inline-question" aria-label="Agent question">
      <div className="inline-question-heading">
        {answer ? <Check size={14} aria-hidden="true" /> : <HelpCircle size={14} aria-hidden="true" />}
        <span>{answer ? "Answered" : pending ? "Agent needs your input" : "Question · unanswered"}</span>
      </div>
      <p>{question}</p>
      {answer ? <div className="inline-question-answer"><span>Your answer</span><p>{answer}</p></div> :
        pending && onAnswer ? (
          <form onSubmit={(event) => {
            event.preventDefault();
            if (draft.trim() && onAnswer(draft.trim())) setDraft("");
          }}>
            <label className="sr-only" htmlFor={id}>Your answer</label>
            <textarea id={id} value={draft} onChange={(event) => setDraft(event.target.value)}
              placeholder="Type your answer…" rows={2} />
            <button type="submit" className="btn btn-primary btn-sm" disabled={!draft.trim()}>Send answer</button>
          </form>
        ) : null}
    </section>
  );
}
