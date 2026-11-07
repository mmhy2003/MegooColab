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
export type RepoChoices = S["RepoChoicesOut"];
export type WebhookInfo = S["WebhookOut"];
export type WebhookRenewed = S["WebhookRenewOut"];

/** The host's own name, as its people say it. */
export const HOST_NAME: Record<GitKind, string> = { github: "GitHub", gitlab: "GitLab", gitea: "Gitea" };

/** How to add a repository's webhook by hand, in each host's own words. */
export const HOOK_STEPS: Record<GitKind, string[]> = {
  github: [
    "Open the repository › Settings › Webhooks › Add webhook.",
    "Paste the Payload URL, set Content type to application/json, and paste the Secret.",
    "Choose Let me select individual events: Pull requests, Pull request reviews, Pull request review comments, Issue " +
      "comments, Pushes, Check runs, Check suites and Statuses.",
    "Save. GitHub sends a test event, and this turns to working.",
  ],
  gitlab: [
    "Open the project › Settings › Webhooks › Add new webhook.",
    "Paste the URL, and paste the secret into Secret token.",
    "Under Trigger, tick Push events, Comments, Merge request events and Pipeline events.",
    "Save, then Test › Merge request events: this turns to working.",
  ],
  gitea: [
    "Open the repository › Settings › Webhooks › Add webhook › Gitea.",
    "Paste the Target URL, choose the JSON content type, and paste the Secret.",
    "Choose Custom events: Push, Pull request, Pull request synchronized, Pull request comment, Pull request reviewed " +
      "(approved, rejected, comment), Issue comment and Status.",
    "Add the webhook, then Test delivery: this turns to working.",
  ],
};

const HOOK_ERRORS: Record<string, string> = {
  forbidden: "This token can't manage webhooks. Use the steps above, or give the token webhook permission.",
  not_found: "The host can't find this repository with this token.",
};

/** Why Create it for me couldn't, in plain words. */
export function hookError(code: string): string {
  return HOOK_ERRORS[code] ?? gitTestError(code);
}

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

/** One permission (or scope) a token needs; `access` for a fine-grained one ("Read", "Read and write"). */
export type TokenPermission = { name: string; access?: "Read" | "Read and write" };
/** One reason a token needs some access: what it lets MegooColab do, and the permissions for it. */
export type TokenNeed = {
  why: string;
  required: boolean;
  permissions: TokenPermission[];
  /** a plain line under the permissions */
  note?: string;
  /** a line to heed, set apart */
  warning?: string;
};
/** A kind of token a host offers (GitHub: fine-grained or classic), what it needs, and its new-token page. */
export type TokenVariant = { label: string; needs: TokenNeed[]; newTokenPath: string; newTokenLabel: string };

const R = "Read" as const;
const RW = "Read and write" as const;

/** What the access token needs, per host: the first variant is the one shown first. Every list starts with the one
 * required reason (follow pull requests), then the two optional ones (webhooks, an agent's review and merge). */
export const TOKEN_NEEDS: Record<GitKind, TokenVariant[]> = {
  github: [
    {
      label: "Fine-grained token",
      newTokenPath: "/settings/personal-access-tokens/new",
      newTokenLabel: "Create a token on GitHub",
      needs: [
        {
          why: "Follow pull requests",
          required: true,
          permissions: [
            { name: "Contents", access: R },
            { name: "Metadata", access: R },
            { name: "Pull requests", access: R },
            { name: "Commit statuses", access: R },
          ],
          warning:
            "A fine-grained token can't read check runs, where GitHub Actions reports, so their results show as " +
            "unknown. A classic token shows them.",
        },
        {
          why: "Set up webhooks in one click",
          required: false,
          permissions: [{ name: "Webhooks", access: RW }],
          note: "Without it, you add each webhook on GitHub yourself.",
        },
        {
          why: "Let an agent review and merge",
          required: false,
          permissions: [{ name: "Pull requests", access: RW }, { name: "Contents", access: RW }],
        },
      ],
    },
    {
      label: "Classic token",
      newTokenPath: "/settings/tokens/new?description=MegooColab&scopes=repo",
      newTokenLabel: "Create a classic token on GitHub",
      needs: [
        {
          why: "Follow pull requests",
          required: true,
          permissions: [{ name: "repo" }],
          note: "Reads everything, check runs included, but also allows writing.",
        },
        {
          why: "Set up webhooks in one click",
          required: false,
          permissions: [{ name: "admin:repo_hook" }],
          note: "Without it, you add each webhook on GitHub yourself.",
        },
        { why: "Let an agent review and merge", required: false, permissions: [], note: "Covered by repo." },
      ],
    },
  ],
  gitlab: [
    {
      label: "Access token",
      newTokenPath: "/-/user_settings/personal_access_tokens?name=MegooColab&scopes=read_api",
      newTokenLabel: "Create a token on GitLab",
      needs: [
        { why: "Follow merge requests", required: true, permissions: [{ name: "read_api" }] },
        {
          why: "Set up webhooks in one click",
          required: false,
          permissions: [{ name: "api" }],
          note: "With Maintainer on the project. Without it, you add each webhook on GitLab yourself.",
        },
        { why: "Let an agent review and merge", required: false, permissions: [{ name: "api" }], note: "With Developer or more on the project." },
      ],
    },
  ],
  gitea: [
    {
      label: "Access token",
      newTokenPath: "/user/settings/applications",
      newTokenLabel: "Create a token on Gitea",
      needs: [
        { why: "Follow pull requests", required: true, permissions: [{ name: "read:repository" }] },
        {
          why: "Set up webhooks in one click",
          required: false,
          permissions: [{ name: "write:repository" }],
          note: "Without it, you add each webhook on Gitea yourself.",
        },
        { why: "Let an agent review and merge", required: false, permissions: [{ name: "write:repository" }] },
      ],
    },
  ],
};

/** The host's new-token page under the server's address, or null without a real http(s) address. */
export function newTokenUrl(base: string, path: string): string | null {
  const root = base.trim().replace(/\/+$/, "");
  return /^https?:\/\/[^/\s]+/.test(root) ? `${root}${path}` : null;
}

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

const CHECKS: Record<string, string> = {
  success: "checks passed",
  failure: "checks failed",
  pending: "checks pending",
  unknown: "checks unknown",
};
const REVIEW: Record<string, string> = { approved: "approved", changes_requested: "changes requested", unknown: "review unknown" };

/** What a token needs to read pull requests, per host (the words of its token hint). */
const NEEDS_TO_READ: Record<GitKind, string> = {
  github: "Pull requests and Commit statuses (read)",
  gitlab: "the read_api scope",
  gitea: "read:repository",
};

/** Why a pull request couldn't be read, in plain words. `kind` is the host (null when unknown). */
export function pullRequestProblem(code: string, kind: GitKind | null): string {
  const host = kind ? HOST_NAME[kind] : "The git host";
  switch (code) {
    case "forbidden":
      return `${host} refused the token (forbidden). It needs ${kind ? NEEDS_TO_READ[kind] : "read access to pull requests"}.`;
    case "unauthorized":
      return `${host} rejected the token. It may have expired or been revoked.`;
    case "not_found":
      return "The token can't see this repository or pull request.";
    case "rate_limited":
      return `${host} is limiting requests. MegooColab will try again.`;
    case "unreachable":
      return `${host} couldn't be reached.`;
    case "bad_token":
      return "The saved token can't be read. Save it again in Settings › Git.";
    case "url_mismatch":
      return "The pull request isn't on this connection's address.";
    default:
      return `${host} sent something MegooColab didn't understand.`;
  }
}

/** What a partial read couldn't see ("checks", "review" or "checks,review"), or null when it saw everything. `kind`
 * is the host (null when unknown): GitHub gives no fine-grained token a way to read check runs, so it says that. */
export function limitedText(limited: string | null | undefined, kind: GitKind | null = null): string | null {
  const parts = (limited ?? "").split(",");
  const out = [
    parts.includes("checks") &&
      (kind === "github"
        ? "Checks unknown: GitHub doesn't let a fine-grained token read check runs, where GitHub Actions reports. A classic token with repo shows them."
        : "Checks unknown: the token can't read commit statuses or checks."),
    parts.includes("review") && "Review unknown: the token can't read reviews.",
  ].filter(Boolean);
  return out.length ? out.join(" ") : null;
}

/** "PR open · checks pending · approved", "PR merged", "PR (not tracked)", "PR · can't read". */
export function pullRequestText(pr: PullRequest): string {
  if (pr.error) return "PR · can't read";
  if (!pr.tracked) return "PR (not tracked)";
  if (pr.state !== "open") return `PR ${pr.state}`;
  return ["PR open", CHECKS[pr.checks], REVIEW[pr.review]].filter(Boolean).join(" · ");
}
