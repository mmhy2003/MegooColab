import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/queries";
import type { AgentProgram, AgentRun, AnswerMode, ProjectAgent } from "@/lib/types";

export type AgentStatus = "online" | "busy" | "offline";

export const PROGRAM_LABEL: Record<AgentProgram, string> = {
  claude_code: "Claude Code",
  codex: "Codex",
};

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
  repository_not_matched: "the agent's folder doesn't match any of the project's repositories",
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
