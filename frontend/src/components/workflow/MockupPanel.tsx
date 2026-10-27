"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import { useDocuments, useMockups, useWorkflow } from "@/lib/workflow";

import { MockupFrame } from "./MockupFrame";

const FIELD = "w-full rounded border border-line bg-surface-2 px-2 py-1 text-sm disabled:opacity-60";
const MAX_FEEDBACK = 4000;

/**
 * The task's mockups as the agent shows them (WF-6d): the newest version, live, with earlier ones a click away.
 * A viewer following the newest version moves on when a new one arrives; one looking at an older version stays
 * and gets a "vN is ready" button. Feedback goes where the workflow waits: the open question, or a request for
 * changes to the submitted design. Approving the version the design was submitted with approves the design.
 */
export function MockupPanel({ taskKey, disabled = false }: { taskKey: string; disabled?: boolean }) {
  const client = useQueryClient();
  const mockups = useMockups(taskKey);
  const workflow = useWorkflow(taskKey);
  const documents = useDocuments(taskKey);
  // null follows the newest version; `seen` is the newest version when the viewer picked an older one
  const [viewing, setViewing] = useState<{ version: number; seen: number } | null>(null);
  const [compare, setCompare] = useState<number | null>(null);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const list = mockups.data ?? [];
  if (mockups.error) return <p className="text-sm text-pink">{errorMessage(mockups.error)}</p>;
  if (list.length === 0) return null;

  const newest = list[list.length - 1];
  const shown = (viewing && list.find((m) => m.version === viewing.version)) || newest;
  const other = compare !== null ? list.find((m) => m.version === compare && m.version !== shown.version) : undefined;
  const ready = viewing && newest.version > viewing.seen ? newest : undefined;

  const wf = workflow.data;
  const canAct = wf?.can_act === true && !disabled;
  const pending = (documents.data ?? []).find((d) => d.kind === "design" && d.status === "submitted");
  const awaitingDesign = wf?.needs === "design_approval" && !!pending;
  const asking = wf?.needs === "question" && !!wf.open_question_id;
  const linked = pending?.mockup_id ? list.find((m) => m.id === pending.mockup_id) : undefined;

  const pick = (version: number) => {
    setViewing(version === newest.version ? null : { version, seen: newest.version });
    setError(null);
  };

  const act = async (fn: () => Promise<unknown>, after?: () => void) => {
    setError(null);
    setBusy(true);
    try {
      await fn();
      after?.();
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

  const sendFeedback = () => {
    const text = feedback.trim();
    if (!text) {
      setError("Add a comment explaining what should change.");
      return;
    }
    if (asking) {
      void act(() => api(`/api/tasks/${taskKey}/questions/${wf!.open_question_id}/answer`, { method: "POST", json: { text } }), () => setFeedback(""));
    } else if (awaitingDesign) {
      void act(
        () => api(`/api/tasks/${taskKey}/documents/design/${pending!.version}/decision`, { method: "POST", json: { approve: false, comment: text } }),
        () => setFeedback(""),
      );
    }
  };

  const approve = () =>
    void act(() => api(`/api/tasks/${taskKey}/documents/design/${pending!.version}/decision`, { method: "POST", json: { approve: true, comment: null } }));

  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Mockup versions" className="flex flex-wrap gap-1">
          {list.map((m) => (
            <button
              key={m.id}
              type="button"
              aria-pressed={m.version === shown.version}
              onClick={() => pick(m.version)}
              className={`rounded border px-2 py-0.5 text-xs ${m.version === shown.version ? "border-cyan font-semibold text-cyan-ink" : "border-line text-muted hover:border-cyan"}`}
            >
              v{m.version}
            </button>
          ))}
        </div>
        <span className="text-xs text-muted">
          v{shown.version} of {newest.version}
        </span>
        {ready && (
          <button type="button" onClick={() => setViewing(null)} className="rounded-full bg-cyan/15 px-2 py-0.5 text-xs font-semibold text-cyan-ink">
            v{ready.version} is ready
          </button>
        )}
        {list.length > 1 && (
          <label className="ml-auto flex items-center gap-1 text-xs text-muted">
            Compare with
            <select
              aria-label="Compare with"
              className="rounded border border-line bg-surface-2 px-1 py-0.5 text-xs"
              value={other ? String(other.version) : ""}
              onChange={(e) => setCompare(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">—</option>
              {list
                .filter((m) => m.version !== shown.version)
                .map((m) => (
                  <option key={m.id} value={m.version}>
                    v{m.version}
                  </option>
                ))}
            </select>
          </label>
        )}
      </div>

      <div className={other ? "grid gap-3 lg:grid-cols-2" : ""}>
        <MockupFrame key={shown.id} mockupId={shown.id} version={shown.version} title={shown.title} />
        {other && <MockupFrame key={other.id} mockupId={other.id} version={other.version} title={other.title} />}
      </div>

      {canAct && linked && shown.id === linked.id && awaitingDesign && (
        <Button disabled={busy} onClick={approve}>
          Approve this version
        </Button>
      )}
      {linked && awaitingDesign && shown.version < linked.version && <p className="text-xs text-muted">Older version</p>}

      {canAct && (
        <div className="space-y-2">
          <label className="block space-y-1 text-xs text-muted">
            Feedback
            <textarea
              aria-label="Feedback"
              rows={3}
              maxLength={MAX_FEEDBACK}
              className={FIELD}
              value={feedback}
              disabled={!asking && !awaitingDesign}
              onChange={(e) => setFeedback(e.target.value)}
            />
          </label>
          {asking ? (
            <Button disabled={busy} onClick={sendFeedback}>
              Send feedback
            </Button>
          ) : awaitingDesign ? (
            <Button variant="danger" disabled={busy} onClick={sendFeedback}>
              Request changes
            </Button>
          ) : (
            <p className="text-xs text-muted">The agent is working. You can reply when it asks a question or submits the design.</p>
          )}
        </div>
      )}
      {error && (
        <p role="alert" className="text-xs text-pink">
          {error}
        </p>
      )}
    </div>
  );
}
