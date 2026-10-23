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
