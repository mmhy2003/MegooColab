"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";

type S = components["schemas"];

export type GitConnection = S["GitConnectionOut"];
export type GitKind = GitConnection["kind"];
export type GitConnectionTest = S["GitConnectionTest"];
export type ConnectionRef = S["ConnectionRef"];
export type PullRequest = S["PullRequestOut"];

export const GIT_KINDS: { value: GitKind; label: string }[] = [
  { value: "github", label: "GitHub" },
  { value: "gitlab", label: "GitLab" },
  { value: "gitea", label: "Gitea / Forgejo" },
];

export const gitKeys = {
  connections: () => ["git", "connections"] as const,
  names: () => ["git", "names"] as const,
};

export function useGitConnections() {
  return useQuery({ queryKey: gitKeys.connections(), queryFn: () => api<GitConnection[]>("/api/admin/git-connections") });
}

/** Connection names any signed-in user may see, for linking a project's repositories. */
export function useConnectionNames() {
  return useQuery({ queryKey: gitKeys.names(), queryFn: () => api<ConnectionRef[]>("/api/git/connections") });
}

export function webhookUrl(connectionId: string): string {
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return `${origin}/api/git/webhooks/${connectionId}`;
}

const TEST_ERRORS: Record<string, string> = {
  unauthorized: "The git host refused the token.",
  not_found: "Not found: check the base URL.",
  rate_limited: "The git host is rate-limiting this token. Try again later.",
  unreachable: "Couldn't reach the git host.",
  bad_response: "The git host gave an unexpected answer.",
};

export function gitTestError(code: string | null | undefined): string {
  return TEST_ERRORS[code ?? ""] ?? "The connection test failed.";
}

const CHECKS: Record<string, string> = { success: "checks passed", failure: "checks failed", pending: "checks pending" };
const REVIEW: Record<string, string> = { approved: "approved", changes_requested: "changes requested" };

/** "PR open · checks pending · approved", "PR merged", "PR (not tracked)". */
export function pullRequestText(pr: PullRequest): string {
  if (!pr.tracked) return "PR (not tracked)";
  if (pr.state !== "open") return `PR ${pr.state}`;
  return ["PR open", CHECKS[pr.checks], REVIEW[pr.review]].filter(Boolean).join(" · ");
}
