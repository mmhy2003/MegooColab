"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import type { ReviewDetail } from "@/lib/types";

const SEVERITIES = [
  { id: "critical", label: "Critical" },
  { id: "important", label: "Important" },
  { id: "minor", label: "Minor" },
] as const;

/** Findings grouped by severity. Every field is agent-written, so it is shown as plain text only. */
export function ReviewFindings({ scope, step, round, verdict, findings }: ReviewDetail) {
  return (
    <div className="space-y-2 rounded border border-line p-2 text-xs">
      <p className="text-muted">
        {scope === "final" ? "Final review" : `Review of step ${step ?? "?"}`} · round {round} ·{" "}
        {verdict === "approved" ? "approved" : "changes requested"}
      </p>
      {findings.length === 0 && <p>No findings.</p>}
      {SEVERITIES.map(({ id, label }) => {
        const group = findings.filter((f) => f.severity === id);
        if (group.length === 0) return null;
        return (
          <section key={id} aria-label={`${label} findings`}>
            <h4 className="font-semibold">
              {label} ({group.length})
            </h4>
            <ul className="space-y-1">
              {group.map((f, i) => (
                <li key={i}>
                  {f.file && (
                    <code className="mr-1 break-all">
                      {f.file}
                      {f.line ? `:${f.line}` : ""}
                    </code>
                  )}
                  <span className="break-words">{f.summary}</span>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

/** The findings of one review, fetched only when the person opens them. */
export function ReviewResult({ taskKey, reviewId, total }: { taskKey: string; reviewId: string; total: number }) {
  const [open, setOpen] = useState(false);
  const review = useQuery({
    queryKey: qk.review(taskKey, reviewId),
    queryFn: () => api<ReviewDetail>(`/api/tasks/${taskKey}/reviews/${reviewId}`),
    enabled: open,
  });
  if (total === 0) return null;
  return (
    <div className="mt-1 space-y-1">
      <button type="button" className="text-cyan-ink underline" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? "Hide findings" : `Show findings (${total})`}
      </button>
      {open && review.error && <p className="text-pink">{errorMessage(review.error)}</p>}
      {open && !review.data && !review.error && <p>Loading…</p>}
      {open && review.data && <ReviewFindings {...review.data} />}
    </div>
  );
}
