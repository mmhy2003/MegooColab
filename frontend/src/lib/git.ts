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

/** The hosted services: a connection to one needs no address of its own. Gitea and Forgejo are always self-hosted. */
export const HOSTED: Partial<Record<GitKind, { label: string; url: string }>> = {
  github: { label: "GitHub.com", url: "https://github.com" },
  gitlab: { label: "GitLab.com", url: "https://gitlab.com" },
};

/** What the access token needs, per host. */
export const TOKEN_HELP: Record<GitKind, string> = {
  github:
    "Read access to your repositories and pull requests: a fine-grained token with Contents, Metadata and Pull " +
    "requests (read), or a classic token with repo. Optional, for one-click webhook setup: Webhooks (read and write), " +
    "or admin:repo_hook. Optional, for an agent to review and merge: Pull requests and Contents (read and write).",
  gitlab:
    "Read access to your repositories and merge requests: the read_api scope. Optional, for one-click webhook setup: " +
    "the api scope, with Maintainer on the project. Optional, for an agent to review and merge: api, with Developer " +
    "or more.",
  gitea:
    "Read access to your repositories (read:repository). Optional, for one-click webhook setup: write:repository. " +
    "Optional, for an agent to review and merge: write:repository.",
};

export const TOKEN_DOCS: Record<GitKind, string> = {
  github: "https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens",
  gitlab: "https://docs.gitlab.com/user/profile/personal_access_tokens/",
  gitea: "https://docs.gitea.com/development/api-usage",
};

const TEST_ERRORS: Record<string, string> = {
  unauthorized: "The git host refused the token.",
  forbidden: "The token isn't allowed to do this.",
  bad_token: "The saved token can't be used (the server's SECRET_KEY changed, or it has odd characters). Save it again.",
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
