"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { citationText, type Question, questionKeys } from "@/lib/questions";

const ANSWER_MAX = 20000;
const REASON_MAX = 500;
const FIELD = "w-full rounded border border-line bg-surface-2 px-3 py-2 text-sm text-fg focus:border-cyan focus:outline-none";

/** The agent's owner reviews a draft answer (manual mode, A2A-4): approve it, edited or not, or reject it. */
export function DraftReview({ question }: { question: Question }) {
  const client = useQueryClient();
  const draft = question.draft;
  const [text, setText] = useState(draft?.answer_md ?? "");
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!question.can_approve || !draft) return null;

  const act = async (path: "approve" | "reject", json: unknown) => {
    setError(null);
    setBusy(true);
    try {
      await api(`/api/questions/${question.id}/${path}`, { method: "POST", json });
      await client.invalidateQueries({ queryKey: questionKeys.all });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-label="Draft answer" className="card space-y-3 p-4">
      <h2 className="text-sm font-semibold">Draft by {draft.agent?.name ?? "your agent"} — awaiting your approval</h2>
      <textarea
        aria-label="Draft answer text"
        rows={8}
        maxLength={ANSWER_MAX}
        className={FIELD}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {draft.citations.length > 0 && (
        <ul aria-label="Draft sources" className="space-y-1">
          {draft.citations.map((c) => (
            <li key={citationText(c)} className="font-mono text-xs">
              {citationText(c)}
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={busy || !text.trim()}
          onClick={() => void act("approve", text.trim() === draft.answer_md ? {} : { answer_md: text.trim() })}
        >
          Approve
        </Button>
        {!rejecting && (
          <Button variant="danger" disabled={busy} onClick={() => setRejecting(true)}>
            Reject
          </Button>
        )}
      </div>
      {rejecting && (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            void act("reject", { reason: reason.trim() });
          }}
        >
          <label htmlFor="q-reject" className="text-xs tracking-wider text-muted uppercase">
            Why is it wrong? Another agent will try.
          </label>
          <input
            id="q-reject"
            required
            maxLength={REASON_MAX}
            className={FIELD}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="flex gap-2">
            <Button type="submit" variant="danger" disabled={busy || !reason.trim()}>
              Reject draft
            </Button>
            <Button variant="ghost" onClick={() => setRejecting(false)}>
              Cancel
            </Button>
          </div>
        </form>
      )}
      {error && (
        <p role="alert" className="text-sm text-pink">
          {error}
        </p>
      )}
    </section>
  );
}
