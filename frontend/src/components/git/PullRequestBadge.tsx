import { GitMerge, GitPullRequest, GitPullRequestClosed } from "lucide-react";

import { pullRequestText, type PullRequest } from "@/lib/git";

const TONE: Record<string, string> = {
  merged: "border-green text-green-ink",
  closed: "border-pink text-pink",
  failure: "border-pink text-pink",
  success: "border-green text-green-ink",
  pending: "border-amber text-amber",
};

/** The pull request's state in words (never colour alone), linking to it on the git host. */
export function PullRequestBadge({ pr }: { pr: PullRequest }) {
  const Icon = pr.state === "merged" ? GitMerge : pr.state === "closed" ? GitPullRequestClosed : GitPullRequest;
  const tone = (pr.tracked && (TONE[pr.state] ?? TONE[pr.checks])) || "border-line text-muted";
  return (
    <a
      href={pr.url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e) => e.stopPropagation()}
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] no-underline ${tone}`}
    >
      <Icon size={12} aria-hidden />
      {pullRequestText(pr)}
    </a>
  );
}
