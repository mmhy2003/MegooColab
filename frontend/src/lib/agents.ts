import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/queries";
import type { AgentProgram, AgentRun, AnswerMode, ModelOption, ProjectAgent } from "@/lib/types";

export type AgentStatus = "online" | "busy" | "offline";

export const PROGRAM_LABEL: Record<AgentProgram, string> = {
  claude_code: "Claude Code",
  codex: "Codex",
  omp: "OMP",
};

/** The model a new agent starts on (the server's DEFAULT_MODELS; "" is the program's own default); its owner can
 * pick another or none. OMP works with many providers, so it starts on what its owner set up in OMP. */
export const DEFAULT_MODEL: Record<AgentProgram, string> = {
  claude_code: "Opus 5.5",
  codex: "GPT-6.1 Sol",
  omp: "",
};

/** A model name as an id, as the runner compares them: "GPT-6.1 Sol" and "gpt-6.1-sol" are the same model. */
export function modelKey(name: string): string {
  return name.toLowerCase().trim().split(/\s+/).join("-");
}

/** The effort levels to offer for a model whose own levels aren't known yet (before the agent's first run). */
export const COMMON_EFFORTS = ["low", "medium", "high", "xhigh", "max"].map((value) => ({ value, name: effortName(value) }));

/** "high" as "High", "extra_high" as "Extra High", as the agents name their levels. */
export function effortName(value: string): string {
  return value
    .split(/[_\s-]+/)
    .map((part) => (part ? part.charAt(0).toUpperCase() + part.slice(1) : part))
    .join(" ");
}

/** The model the agent offered that a saved name means (its value, its name, or either written as an id); null is
 * the program's default, which the "default" entry stands for. */
export function findModel(knownModels: ModelOption[], m: string | null): ModelOption | undefined {
  if (m === null) return knownModels.find((k) => k.value === "default");
  return knownModels
    .filter((k) => k.value !== "default")
    .find((k) => k.value === m || [k.value, k.name].some((n) => modelKey(n) === modelKey(m)));
}

/** The effort levels a model offers ("default" aside); an unknown model (typed, or before the agent's first run) may
 * have any of the usual levels, which the runner checks. */
export function effortLevels(knownModels: ModelOption[], m: string | null): { value: string; name: string }[] {
  const entry = findModel(knownModels, m);
  return entry ? entry.efforts.filter((e) => e.value !== "default") : COMMON_EFFORTS;
}

/** A level and a saved effort are the same, by value or by name, case and spaces aside. */
export function sameEffort(level: { value: string; name: string }, effort: string): boolean {
  return modelKey(level.value) === modelKey(effort) || modelKey(level.name) === modelKey(effort);
}

/** The workflow stages an agent can give a model and effort of their own (the server's STAGE_ROWS). */
export type StageKey = "design" | "plan" | "build" | "review" | "finish";
export type StageModels = Partial<Record<StageKey, { model?: string | null; effort?: string | null }>>;

export const STAGE_ROWS: { key: StageKey; label: string; note?: string }[] = [
  { key: "design", label: "Design" },
  { key: "plan", label: "Plan" },
  { key: "build", label: "Build", note: "steps and their fixes" },
  { key: "review", label: "Review", note: "step, final and pull request reviews" },
  { key: "finish", label: "Finish" },
];

/** The stages with no model of their own whose effort the agent's model (once changed to agentModel) doesn't offer. */
export function staleStageEfforts(rows: StageModels, knownModels: ModelOption[], agentModel: string | null): StageKey[] {
  const levels = effortLevels(knownModels, agentModel);
  return STAGE_ROWS.map((r) => r.key).filter((key) => {
    const row = rows[key];
    return !!row && !row.model && !!row.effort && !levels.some((l) => sameEffort(l, row.effort!));
  });
}

/** The stages as saved: only the keys set, and no stage with neither. */
export function cleanStages(rows: StageModels): StageModels {
  const out: StageModels = {};
  for (const { key } of STAGE_ROWS) {
    const row = rows[key];
    const kept = { ...(row?.model ? { model: row.model } : {}), ...(row?.effort ? { effort: row.effort } : {}) };
    if (Object.keys(kept).length > 0) out[key] = kept;
  }
  return out;
}

export const ANSWER_MODE_HELP: Record<AnswerMode, string> = {
  manual: "Manual: you approve each answer before it's sent to another agent",
  auto: "Auto: the agent's answers are sent to other agents without your approval",
};

/** Windows drive (C:\ or C:/), UNC (\\server\share) or POSIX (/home/me) absolute path. */
export function isAbsolutePath(path: string): boolean {
  return /^[A-Za-z]:[\\/]/.test(path) || path.startsWith("\\\\") || path.startsWith("/");
}

const RUN_REASON: Record<string, string> = {
  runner_disconnected: "the runner disconnected",
  runner_unauthorized: "the runner's token was revoked",
  owner_deactivated: "the owner was deactivated",
  user_deactivated: "the owner or requester was deactivated",
  owner_lost_access: "the owner lost access to this project",
  busy: "the agent was busy",
  agent_error: "the agent hit an error",
  not_bound: "the agent isn't set up for this project",
  agent_not_bound: "the agent isn't set up for this project",
  // the runner's failure codes
  mcp_http_unsupported: "the agent can't reach MegooColab's MCP server over HTTP",
  worktree_failed: "the runner couldn't prepare the task's worktree",
  start_branch_missing: "the branch to start from doesn't exist",
  start_branch_fetch_failed: "the runner couldn't reach the repository to fetch the branch to start from",
  repository_not_matched: "the agent's folder doesn't match any of the project's repositories",
  model_unavailable: "the model chosen for this agent isn't available — pick another on My agents",
  effort_unavailable: "the effort chosen for this agent isn't available for its model — pick another on My agents",
  files_failed: "the runner couldn't write the design and plan files",
  commit_failed: "the runner couldn't commit the design and plan documents",
  adapter_start_failed: "the agent program didn't start",
  initialize_failed: "the agent program didn't respond when starting",
  session_failed: "the agent couldn't open a session",
  prompt_failed: "the agent stopped while working",
  invalid_run_files: "the run's files were not valid",
  git_state_unreadable:
    "the runner couldn't read the repository's state, or the worktree isn't on its task branch, so a read-only run can't be checked",
};

/** Plain words for a run's reason code; an unknown code stays readable. */
export function runReasonText(code: string): string {
  return RUN_REASON[code] ?? code.replace(/_/g, " ");
}

export function asAgentStatus(status: string): AgentStatus {
  return status === "online" || status === "busy" ? status : "offline";
}

export function useProjectAgents(projectKey: string) {
  return useQuery({ queryKey: qk.projectAgents(projectKey), queryFn: () => api<ProjectAgent[]>(`/api/projects/${projectKey}/agents`) });
}

/** Runs for a task, newest first. */
export function useAgentRuns(taskKey: string) {
  return useQuery({ queryKey: qk.agentRuns(taskKey), queryFn: () => api<AgentRun[]>(`/api/tasks/${taskKey}/agent-runs`) });
}
