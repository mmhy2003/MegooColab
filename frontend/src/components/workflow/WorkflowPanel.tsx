"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Bot, ExternalLink, GitBranch } from "lucide-react";
import { useState } from "react";

import { AgentStatusDot } from "@/components/agents/AgentStatusDot";
import { Button } from "@/components/ui/Button";
import { api, ApiError } from "@/lib/api";
import { runReasonText, useAgentRuns } from "@/lib/agents";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import type { AgentRun, ProjectAgent } from "@/lib/types";
import {
  ACCEPTABLE_REASONS,
  FINISHING_LABEL,
  STAGES,
  escalationReasonText,
  statusLine,
  useWorkflow,
  type FinishingOption,
} from "@/lib/workflow";

import { StageTrack } from "./StageTrack";

const FIELD = "w-full rounded border border-line bg-surface-2 px-2 py-1 text-sm disabled:opacity-60";
const ENFORCEMENT_TEXT = {
  enforced: "Rules enforced by MegooColab",
  partially_enforced: "Partly enforced: the agent changed the repository when it should not have",
  unenforced: "Not enforced: the work happens outside MegooColab's runner",
} as const;

function runLine(run: AgentRun): string {
  const detail = run.summary ?? (run.reason ? runReasonText(run.reason) : null);
  const where = run.workflow_role ? `${run.step ? `step ${run.step} · ` : ""}${run.workflow_role} · ` : "";
  return `${where}${run.status} · ${run.policy === "read_only" ? "read-only" : "workspace"}${detail ? ` · ${detail}` : ""}`;
}

export function WorkflowPanel({
  taskKey,
  agent,
  unassigned = false,
  disabled = false,
}: {
  taskKey: string;
  agent?: ProjectAgent;
  /** the task has no agent assignee (decided from the task, so it holds while agents load) */
  unassigned?: boolean;
  disabled?: boolean;
}) {
  const client = useQueryClient();
  const workflow = useWorkflow(taskKey);
  const runs = useAgentRuns(taskKey);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showRuns, setShowRuns] = useState(false);

  const wf = workflow.data;
  if (workflow.error) return <p className="text-sm text-pink">{errorMessage(workflow.error)}</p>;
  if (!wf) return <p className="text-sm text-muted">Loading…</p>;

  // after any action (also a failed one: a 409 means the state moved on) show what the server now says
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: qk.workflow(taskKey) }),
      client.invalidateQueries({ queryKey: qk.agentRuns(taskKey) }),
      client.invalidateQueries({ queryKey: qk.activity(taskKey) }),
      client.invalidateQueries({ queryKey: qk.task(taskKey) }),
      client.invalidateQueries({ queryKey: ["documents"] }),
      client.invalidateQueries({ queryKey: ["document"] }),
      client.invalidateQueries({ queryKey: ["mockups"] }),
    ]);
  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    setBusy(true);
    try {
      await fn();
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
      if (err instanceof ApiError && err.status === 409) await refresh();
    } finally {
      setBusy(false);
    }
  };
  const post = (path: string, json?: unknown) => run(() => api(`/api/tasks/${taskKey}/workflow/${path}`, { method: "POST", json }));

  const agentDriven = !!agent && (wf.driver !== "manual" || wf.status === "idle");
  const canUse = !!agent?.can_use && !disabled;
  const canDecide = wf.can_act && !disabled;
  const { status } = wf;
  const latest = runs.data?.[0];
  const escalating = status === "waiting_human" && wf.needs === "escalation";
  // set_finishing needs a started workflow and is closed from done on
  const showFinishing = agentDriven && status !== "idle" && status !== "finished" && wf.stage !== "done";
  const showChecklist = unassigned && !agent && wf.can_set_manual && !disabled && status !== "running" && status !== "waiting_human";

  return (
    <section aria-label="Workflow" className="card space-y-3 p-3 text-sm">
      {agent && (
        <p className="flex items-center gap-2">
          <Bot size={14} aria-hidden className="text-cyan-ink" />
          <span className="min-w-0 flex-1 truncate">{agent.name}</span>
          <AgentStatusDot status={agent.status} />
        </p>
      )}
      {agent?.status === "offline" && (
        <p className="text-xs text-muted">Agent offline — the run starts when {agent.owner.name}&apos;s runner connects.</p>
      )}
      <StageTrack stage={wf.stage} status={status} canAct={wf.can_act && !disabled} hideStatus />
      <p className="font-semibold">{statusLine(wf)}</p>
      {!(status === "idle" && !agent) && <p className="text-xs text-muted">{ENFORCEMENT_TEXT[wf.enforcement]}</p>}

      {escalating && (
        <div className="space-y-2 rounded border border-pink/60 p-2">
          <p>{escalationReasonText(wf.escalation_reason)}</p>
          {canDecide ? (
            <div className="flex flex-wrap gap-2">
              <Button disabled={busy} onClick={() => void post("escalation", { action: "retry" })}>Retry</Button>
              {wf.escalation_reason && ACCEPTABLE_REASONS.includes(wf.escalation_reason) && (
                <Button variant="ghost" disabled={busy} onClick={() => void post("escalation", { action: "accept" })}>Accept</Button>
              )}
              <Button variant="danger" disabled={busy} onClick={() => void post("escalation", { action: "pause" })}>Pause</Button>
            </div>
          ) : (
            <p className="text-xs text-muted">
              {wf.can_act ? "This is a read-only view." : "Waiting on the agent’s owner or a project manager."}
            </p>
          )}
        </div>
      )}

      {agentDriven && canUse && (
        <div className="flex flex-wrap gap-2">
          {status === "idle" && <Button disabled={busy} onClick={() => void post("start")}>Start</Button>}
          {(status === "running" || (status === "waiting_human" && !escalating)) && (
            <Button variant="ghost" disabled={busy} onClick={() => void post("pause")}>Pause</Button>
          )}
          {status === "paused" && <Button disabled={busy} onClick={() => void post("resume")}>Resume</Button>}
        </div>
      )}

      {/* a connect_only workflow has no agent here: its assignee, a manager or an admin may pause it, and the
          assignee's next stage tool resumes it */}
      {wf.driver === "connect_only" && (status === "running" || status === "waiting_human") && canDecide && (
        <Button variant="ghost" disabled={busy} onClick={() => void post("pause")}>Pause</Button>
      )}

      {status === "waiting_human" && wf.needs === "human_code_review" && canDecide && (
        <Button disabled={busy} onClick={() => void post("human-review", { approved: true })}>Approve PR</Button>
      )}

      {agentDriven && (
        <div className="space-y-1">
          {showFinishing && !wf.finishing_forced && canDecide ? (
            <label className="block space-y-1 text-xs text-muted">
              Finishing option
              <select
                aria-label="Finishing option"
                className={FIELD}
                disabled={busy}
                value={wf.finishing_option}
                onChange={(e) =>
                  void run(() =>
                    api(`/api/tasks/${taskKey}/workflow/finishing`, { method: "PUT", json: { option: e.target.value as FinishingOption } }),
                  )
                }
              >
                {(Object.keys(FINISHING_LABEL) as FinishingOption[]).map((o) => (
                  <option key={o} value={o}>{FINISHING_LABEL[o]}</option>
                ))}
              </select>
            </label>
          ) : (
            <p className="text-xs text-muted">
              {status === "finished" ? "Finished with" : "Finishes with"}:{" "}
              <span className="text-fg">{FINISHING_LABEL[wf.finishing_option]}</span>
              {wf.finishing_forced && status !== "finished" && (
                <> — required by the project&apos;s human code review setting</>
              )}
            </p>
          )}
        </div>
      )}

      {(wf.branch || wf.pr_url) && (
        <div className="space-y-1 text-xs">
          {wf.branch && (
            <p className="flex items-center gap-1.5">
              <GitBranch size={12} aria-hidden /> <code className="break-all">{wf.branch}</code>
            </p>
          )}
          {wf.pr_url && (
            <a href={wf.pr_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-cyan-ink underline">
              Open the pull request <ExternalLink size={12} aria-hidden />
            </a>
          )}
        </div>
      )}

      {showChecklist && (
        <div className="space-y-2">
          {wf.driver !== "manual" ? (
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => void run(() => api(`/api/tasks/${taskKey}/workflow`, { method: "PATCH", json: { driver: "manual", stage: wf.stage } }))}
            >
              Use stage checklist
            </Button>
          ) : (
            <div role="group" aria-label="Stage checklist" className="flex flex-wrap gap-1">
              {STAGES.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  disabled={busy}
                  aria-pressed={s.id === wf.stage}
                  onClick={() => void run(() => api(`/api/tasks/${taskKey}/workflow`, { method: "PATCH", json: { driver: "manual", stage: s.id } }))}
                  className={`rounded border px-2 py-0.5 text-xs ${s.id === wf.stage ? "border-cyan font-semibold text-cyan-ink" : "border-line text-muted hover:border-cyan"}`}
                >
                  {s.label}
                  {s.id === wf.stage ? " (current)" : ""}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {latest && (
        <div className="space-y-1 text-xs text-muted">
          <p>
            Latest run: <span className="text-fg">{runLine(latest)}</span>
          </p>
          {(runs.data?.length ?? 0) > 1 && (
            <button type="button" className="text-cyan-ink underline" aria-expanded={showRuns} onClick={() => setShowRuns((v) => !v)}>
              {showRuns ? "Hide runs" : `Show all runs (${runs.data!.length})`}
            </button>
          )}
          {showRuns && (
            <ul className="space-y-1">
              {runs.data!.map((r) => (
                <li key={r.id}>{runLine(r)}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {error && <p role="alert" className="text-xs text-pink">{error}</p>}
    </section>
  );
}
