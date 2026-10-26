"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { AnswerForm } from "@/components/questions/AnswerForm";
import { DraftReview } from "@/components/questions/DraftReview";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Markdown } from "@/components/ui/Markdown";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { citationText, type Question, type QuestionStatus, questionKeys, STATUS_TONE, statusLine } from "@/lib/questions";

/** A question, where it stands, and its answer with the code it cites. */
export function QuestionView({ question: q }: { question: Question }) {
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
          <span className="font-mono">{q.ref}</span>
          <span>to {q.target.name}</span>
          {q.from_task && (
            <span>
              · from{" "}
              <Link href={`/projects/${q.from_task.key.split("-")[0]}/tasks/${q.from_task.key.split("-")[1]}`}>
                {q.from_task.key}
              </Link>
            </span>
          )}
          {q.asked_by.user && <span>· asked by {q.asked_by.user.name}{q.asked_by.agent ? ` via ${q.asked_by.agent.name}` : ""}</span>}
        </p>
        <h1 className="text-lg font-bold break-words">{q.title}</h1>
        <p>
          <Badge tone={STATUS_TONE[q.status as QuestionStatus] ?? "muted"}>{statusLine(q)}</Badge>
        </p>
        {q.status === "queued" && q.reject_reason && (
          <p className="text-xs text-muted">A draft was rejected: {q.reject_reason}</p>
        )}
      </header>

      <section aria-label="Question" className="space-y-2">
        <p className="text-sm break-words whitespace-pre-wrap">{q.body}</p>
        {q.context && (
          <details>
            <summary className="cursor-pointer text-xs text-muted">Context</summary>
            <p className="mt-1 text-sm break-words whitespace-pre-wrap">{q.context}</p>
          </details>
        )}
      </section>

      {q.answer_md && (
        <section aria-label="Answer" className="card space-y-3 p-4">
          {q.redacted && (
            <p role="note" className="rounded border border-amber px-3 py-2 text-xs text-amber">
              Secrets were removed from this answer.
            </p>
          )}
          <div className="kb-prose">
            <Markdown>{q.answer_md}</Markdown>
          </div>
          {q.citations.length > 0 && (
            <ul aria-label="Sources" className="space-y-1">
              {q.citations.map((c) => (
                <li key={citationText(c)} className="font-mono text-xs">
                  {citationText(c)}
                </li>
              ))}
            </ul>
          )}
          {q.kb_document_id && <Link href={`/kb/doc/${q.kb_document_id}`}>View in Knowledge Base</Link>}
        </section>
      )}

      <DraftReview key={q.draft?.answer_md ?? ""} question={q} />
      <AnswerForm question={q} />

      {q.can_withdraw && (
        <Button
          variant="ghost"
          onClick={async () => {
            setError(null);
            try {
              await api(`/api/questions/${q.id}/withdraw`, { method: "POST" });
              await client.invalidateQueries({ queryKey: questionKeys.all });
            } catch (err) {
              setError(errorMessage(err));
            }
          }}
        >
          Withdraw
        </Button>
      )}
      {error && (
        <p role="alert" className="text-sm text-pink">
          {error}
        </p>
      )}
    </div>
  );
}
