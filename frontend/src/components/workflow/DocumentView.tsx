"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Markdown } from "@/components/ui/Markdown";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import type { DocKind, DocumentDetail, DocumentInfo } from "@/lib/types";
import { testRunText, useMockups, useRunRecords, useWorkflow, type TestRun } from "@/lib/workflow";

import { MockupFrame } from "./MockupFrame";

const STATUS_TEXT: Record<DocumentInfo["status"], string> = {
  submitted: "waiting for a decision",
  approved: "approved",
  rejected: "rejected",
  superseded: "replaced",
};
const STEP_STATE_TEXT = { pending: "Pending", running: "Running", in_review: "In review", done: "Done" } as const;
const FIELD = "w-full rounded border border-line bg-surface-2 px-2 py-1 text-sm";

export function DocumentView({ taskKey, kind, disabled = false }: { taskKey: string; kind: DocKind; disabled?: boolean }) {
  const client = useQueryClient();
  const workflow = useWorkflow(taskKey);
  const list = useQuery({
    queryKey: qk.documents(taskKey),
    queryFn: () => api<DocumentInfo[]>(`/api/tasks/${taskKey}/documents`),
  });
  const mockups = useMockups(taskKey);
  const records = useRunRecords(taskKey);
  const mockupVersion = new Map((mockups.data ?? []).map((m) => [m.id, m.version]));
  const versions = (list.data ?? []).filter((d) => d.kind === kind).sort((a, b) => a.version - b.version);
  const [picked, setPicked] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // a thread link `#document-<kind>-v<n>` selects that version, also when the hash changes later
  useEffect(() => {
    const fromHash = () => {
      const m = new RegExp(`^#document-${kind}-v(\\d+)$`).exec(window.location.hash);
      if (!m) return;
      setPicked(Number(m[1]));
      setError(null);
      document.getElementById(`document-${kind}`)?.scrollIntoView?.();
    };
    fromHash();
    window.addEventListener("hashchange", fromHash);
    return () => window.removeEventListener("hashchange", fromHash);
  }, [kind]);
  const selected = versions.find((v) => v.version === picked) ?? versions[versions.length - 1];
  const detail = useQuery({
    queryKey: qk.document(taskKey, kind, selected?.version ?? 0),
    queryFn: () => api<DocumentDetail>(`/api/tasks/${taskKey}/documents/${kind}/${selected!.version}`),
    enabled: !!selected,
  });

  if (list.error) return <p className="text-sm text-pink">{errorMessage(list.error)}</p>;
  if (!selected) return null;

  // the mockup the design was submitted with: approving the design approves it
  const linked = detail.data?.mockup_id ? mockups.data?.find((m) => m.id === detail.data!.mockup_id) : undefined;
  const filed = workflow.data?.kb_documents?.find((k) => k.kind === kind)?.document_id;
  const canDecide = selected.status === "submitted" && workflow.data?.can_act === true && !disabled;
  const buildStates = selected.status === "approved" ? workflow.data?.steps : undefined;
  // recorded test runs belong to the plan being built: shown on the approved plan's steps only
  const testRuns = kind === "plan" && selected.status === "approved" ? (records.data?.test_runs ?? []) : [];
  const stepRuns = (n: number): TestRun[] => testRuns.filter((r) => r.stage === "build" && r.step === n);
  const finishRun = testRuns.filter((r) => r.stage === "done").at(-1);
  const unverified = new Set(kind === "plan" ? (records.data?.unverified_steps ?? []) : []);

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
      setError(err instanceof ApiError && err.detail === "already_decided" ? "Someone already decided this version." : errorMessage(err));
    } finally {
      await Promise.all(
        [qk.documents(taskKey), ["document", taskKey], qk.mockups(taskKey), qk.workflow(taskKey), qk.activity(taskKey), qk.task(taskKey)].map((queryKey) =>
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
            className={`rounded border px-2 py-0.5 text-xs ${v.version === selected.version ? "border-cyan font-semibold text-cyan-ink" : "border-line text-muted hover:border-cyan"}`}
          >
            v{v.version} · {STATUS_TEXT[v.status]}
            {v.version === selected.version ? " (selected)" : ""}
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
          {linked && <MockupFrame mockupId={linked.id} version={linked.version} title={linked.title} />}
          {filed && selected.status === "approved" && (
            <p className="text-xs">
              <Link href={`/kb/doc/${filed}`}>View in Knowledge Base</Link>
            </p>
          )}
          <Markdown>{detail.data.body_md}</Markdown>
          {detail.data.steps && detail.data.steps.length > 0 && (
            <ol className="ml-5 list-decimal space-y-1.5">
              {detail.data.steps.map((s, i) => {
                const state = buildStates?.find((b) => b.n === i + 1)?.state;
                const runs = stepRuns(i + 1);
                const latest = runs.at(-1);
                const earlier = runs.slice(0, -1).reverse();
                return (
                  <li key={i}>
                    <span className="font-semibold">{s.title}</span>
                    {state && <span className="text-xs text-muted"> · {STEP_STATE_TEXT[state]}</span>}
                    {s.detail && <p className="text-xs text-muted">{s.detail}</p>}
                    {latest && <p className={`text-xs ${latest.passed ? "text-muted" : "text-pink"}`}>{testRunText(latest)}</p>}
                    {unverified.has(i + 1) && <p className="text-xs text-pink">No test run recorded</p>}
                    {earlier.length > 0 && (
                      <details className="text-xs text-muted">
                        <summary>Earlier runs ({earlier.length})</summary>
                        <ul className="ml-3">
                          {earlier.map((r) => (
                            <li key={r.id}>{testRunText(r)}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
          {finishRun && <p className={`text-xs ${finishRun.passed ? "text-muted" : "text-pink"}`}>Finish verification: {testRunText(finishRun)}</p>}
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
