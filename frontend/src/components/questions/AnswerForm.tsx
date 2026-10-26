"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { type Question, questionKeys } from "@/lib/questions";

const ANSWER_MAX = 20000;

/** A member of the target project answers by hand (A2A-5); an agent still at work is stopped. */
export function AnswerForm({ question }: { question: Question }) {
  const client = useQueryClient();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!question.can_answer) return null;

  return (
    <form
      aria-label="Answer"
      className="card space-y-2 p-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        setBusy(true);
        try {
          await api(`/api/questions/${question.id}/answer`, { method: "POST", json: { answer_md: text.trim() } });
          setText("");
          await client.invalidateQueries({ queryKey: questionKeys.all });
        } catch (err) {
          setError(errorMessage(err));
        } finally {
          setBusy(false);
        }
      }}
    >
      <label htmlFor="q-answer" className="text-xs tracking-wider text-muted uppercase">
        Answer it yourself
      </label>
      <textarea
        id="q-answer"
        rows={5}
        maxLength={ANSWER_MAX}
        placeholder="Markdown. Point to the files you mean, like app/sign.py:3-9."
        className="w-full rounded border border-line bg-surface-2 px-3 py-2 text-sm text-fg focus:border-cyan focus:outline-none"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {question.status === "routed" && (
        <p className="text-xs text-muted">Answering now stops the agent that is working on it.</p>
      )}
      <Button type="submit" disabled={busy || !text.trim()}>
        Post answer
      </Button>
      {error && (
        <p role="alert" className="text-sm text-pink">
          {error}
        </p>
      )}
    </form>
  );
}
