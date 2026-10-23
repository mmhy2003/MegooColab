"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Bot } from "lucide-react";
import { useState } from "react";

import { AgentStatusDot } from "@/components/agents/AgentStatusDot";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { useAgentRuns } from "@/lib/agents";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import type { AgentRun, ProjectAgent, RunPolicy } from "@/lib/types";

const POLICY_LABEL: Record<RunPolicy, string> = {
  read_only: "Read-only: analyse, no edits",
  workspace: "Workspace: may edit inside a task worktree",
};
const FIELD = "w-full rounded border border-line bg-surface-2 px-2 py-1 text-sm disabled:opacity-60";

function runLine(run: AgentRun): string {
  const detail = run.summary ?? run.reason;
  return `${run.status} · ${run.policy === "read_only" ? "read-only" : "workspace"}${detail ? ` · ${detail}` : ""}`;
}

export function AgentRunPanel({ taskKey, agent, disabled }: { taskKey: string; agent: ProjectAgent; disabled: boolean }) {
  const client = useQueryClient();
  const runs = useAgentRuns(taskKey);
  const [policy, setPolicy] = useState<RunPolicy>("read_only");
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const latest = runs.data?.[0];
  const active = latest && (latest.status === "queued" || latest.status === "running") ? latest : undefined;

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    setBusy(true);
    try {
      await fn();
      await Promise.all([
        client.invalidateQueries({ queryKey: qk.agentRuns(taskKey) }),
        client.invalidateQueries({ queryKey: qk.activity(taskKey) }),
      ]);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const canRun = agent.can_use && !disabled && !busy;

  return (
    <section aria-label="Agent" className="card space-y-2 p-3 text-sm">
      <p className="flex items-center gap-2">
        <Bot size={14} aria-hidden className="text-cyan-ink" />
        <span className="min-w-0 flex-1 truncate">{agent.name}</span>
        <AgentStatusDot status={agent.status} />
      </p>
      {agent.status === "offline" && (
        <p className="text-xs text-muted">Agent offline — the run starts when {agent.owner.name}&apos;s runner connects.</p>
      )}
      {latest && (
        <p className="text-xs text-muted">
          Latest run: <span className="text-fg">{runLine(latest)}</span>
        </p>
      )}
      {active && !disabled && (
        <Button variant="danger" disabled={busy} onClick={() => void act(() => api(`/api/agent-runs/${active.id}/cancel`, { method: "POST" }))}>
          Cancel run
        </Button>
      )}
      <label className="block space-y-1 text-xs text-muted">
        Run policy
        <select aria-label="Run policy" className={FIELD} disabled={!canRun} value={policy} onChange={(e) => setPolicy(e.target.value as RunPolicy)}>
          {(Object.keys(POLICY_LABEL) as RunPolicy[]).map((p) => (
            <option key={p} value={p}>{POLICY_LABEL[p]}</option>
          ))}
        </select>
      </label>
      <label className="block space-y-1 text-xs text-muted">
        Prompt (optional)
        <textarea aria-label="Prompt (optional)" rows={3} maxLength={4000} className={FIELD} disabled={!canRun} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      </label>
      <Button
        disabled={!canRun}
        title={agent.can_use ? undefined : "Only the owner, project managers and admins can assign this agent"}
        onClick={() =>
          void act(async () => {
            await api(`/api/tasks/${taskKey}/agent-runs`, { method: "POST", json: { policy, prompt: prompt.trim() || null } });
            setPrompt("");
          })
        }
      >
        Run agent
      </Button>
      {error && <p role="alert" className="text-xs text-pink">{error}</p>}
    </section>
  );
}
