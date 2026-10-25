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
