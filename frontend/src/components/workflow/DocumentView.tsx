"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Markdown } from "@/components/ui/Markdown";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import type { DocKind, DocumentDetail, DocumentInfo } from "@/lib/types";
import { useWorkflow } from "@/lib/workflow";

const STATUS_TEXT: Record<DocumentInfo["status"], string> = {
  submitted: "waiting for a decision",
  approved: "approved",
  rejected: "rejected",
  superseded: "replaced",
};
const STEP_STATE_TEXT = { pending: "Pending", running: "Running", in_review: "In review", done: "Done" } as const;
const FIELD = "w-full rounded border border-line bg-surface-2 px-2 py-1 text-sm";

export function DocumentView({ taskKey, kind }: { taskKey: string; kind: DocKind }) {
  const client = useQueryClient();
  const workflow = useWorkflow(taskKey);
  const list = useQuery({
    queryKey: qk.documents(taskKey),
    queryFn: () => api<DocumentInfo[]>(`/api/tasks/${taskKey}/documents`),
  });
  const mockups = useQuery({
    queryKey: qk.mockups(taskKey),
    queryFn: () => api<{ id: string; version: number }[]>(`/api/tasks/${taskKey}/mockups`),
  });
  const mockupVersion = new Map((mockups.data ?? []).map((m) => [m.id, m.version]));
  const versions = (list.data ?? []).filter((d) => d.kind === kind).sort((a, b) => a.version - b.version);
  const [picked, setPicked] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const selected = versions.find((v) => v.version === picked) ?? versions[versions.length - 1];
  const detail = useQuery({
    queryKey: qk.document(taskKey, kind, selected?.version ?? 0),
    queryFn: () => api<DocumentDetail>(`/api/tasks/${taskKey}/documents/${kind}/${selected!.version}`),
    enabled: !!selected,
  });

  if (list.error) return <p className="text-sm text-pink">{errorMessage(list.error)}</p>;
  if (!selected) return null;

  const canDecide = selected.status === "submitted" && workflow.data?.can_act === true;
  const buildStates = selected.status === "approved" ? workflow.data?.steps : undefined;

  const decide = async (approve: boolean) => {
    setError(null);
    const text = comment.trim();
    if (!approve && !text) {
      setError("Add a comment explaining what should change.");
      return;
    }
    setBusy(true);
    try {
      await api(`/api/tasks/${taskKey}/documents/${kind}/${selected.version}/decision`, {
        method: "POST",
        json: { approve, comment: text || null },
      });
      setComment("");
    } catch (err) {
      setError(err instanceof ApiError && err.status === 409 ? "Someone already decided this version." : errorMessage(err));
    } finally {
      await Promise.all(
        [qk.documents(taskKey), ["document", taskKey], qk.workflow(taskKey), qk.activity(taskKey), qk.task(taskKey)].map((queryKey) =>
          client.invalidateQueries({ queryKey }),
        ),
      );
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3 text-sm">
      <div role="group" aria-label={`${kind} versions`} className="flex flex-wrap gap-1">
        {versions.map((v) => (
          <button
            key={v.version}
            type="button"
            aria-pressed={v.version === selected.version}
            onClick={() => {
              setPicked(v.version);
              setError(null);
            }}
            className={`rounded border px-2 py-0.5 text-xs ${v.version === selected.version ? "border-cyan text-cyan-ink" : "border-line text-muted hover:border-cyan"}`}
          >
            v{v.version} · {STATUS_TEXT[v.status]}
          </button>
        ))}
      </div>
      {detail.error && <p className="text-pink">{errorMessage(detail.error)}</p>}
      {detail.data && (
        <>
          {detail.data.attached_mockup_ids.length > 0 && (
            <ul className="space-y-0.5 text-xs">
              {detail.data.attached_mockup_ids.map((id) => (
                <li key={id}>
                  <a href={`/api/mockups/${id}/view`} target="_blank" rel="noopener noreferrer" className="text-cyan-ink underline">
                    Chosen mockup{mockupVersion.has(id) ? ` v${mockupVersion.get(id)}` : ""}
                  </a>
                </li>
              ))}
            </ul>
          )}
          <Markdown>{detail.data.body_md}</Markdown>
          {detail.data.steps && detail.data.steps.length > 0 && (
            <ol className="ml-5 list-decimal space-y-1.5">
              {detail.data.steps.map((s, i) => {
                const state = buildStates?.find((b) => b.n === i + 1)?.state;
                return (
                  <li key={i}>
                    <span className="font-semibold">{s.title}</span>
                    {state && <span className="text-xs text-muted"> · {STEP_STATE_TEXT[state]}</span>}
                    {s.detail && <p className="text-xs text-muted">{s.detail}</p>}
                  </li>
                );
              })}
            </ol>
          )}
          {detail.data.decision_comment && selected.status === "rejected" && (
            <p className="text-xs text-muted">Rejected: {detail.data.decision_comment}</p>
          )}
        </>
      )}
      {canDecide && (
        <div className="space-y-2">
          <label className="block space-y-1 text-xs text-muted">
            Comment
            <textarea aria-label="Comment" rows={3} maxLength={4000} className={FIELD} value={comment} onChange={(e) => setComment(e.target.value)} />
          </label>
          <div className="flex gap-2">
            <Button disabled={busy} onClick={() => void decide(true)}>Approve</Button>
            <Button variant="danger" disabled={busy} onClick={() => void decide(false)}>Reject</Button>
          </div>
          <p className="text-xs text-muted">A comment is required to reject.</p>
        </div>
      )}
      {error && <p role="alert" className="text-xs text-pink">{error}</p>}
    </div>
  );
}
