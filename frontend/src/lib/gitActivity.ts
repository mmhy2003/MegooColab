import { HOST_NAME, type GitKind } from "@/lib/git";

/** One pull request or branch event on a task's Activity (piece 2), in words: who, what, where and the host. */
export type GitLine = {
  icon: "push" | "opened" | "comment" | "approved" | "changes" | "reviewed" | "checks-passed" | "checks-failed" | "merged" | "closed";
  /** the actor's name; null for a line that is a sentence of its own (checks, the poll's nameless merge or close) */
  lead: string | null;
  /** an agent of MegooColab acted (with the developer's own account on the host) */
  agent: boolean;
  /** the host account behind the line, shown on hover */
  login: string | null;
  text: string;
  host: string | null;
  /** the pull request's or comment's page on the host (http/https only) */
  href: string | null;
  /** an excerpt, shown as plain text */
  quote: string | null;
  /** a line comment's place, e.g. "src/a.py:88" */
  where: string | null;
  /** a review's "N comments" */
  detail: string | null;
};

type Data = Record<string, unknown>;

function str(v: unknown): string | null {
  return typeof v === "string" && v ? v : null;
}

function num(v: unknown): number | null {
  return typeof v === "number" ? v : null;
}

function obj(v: unknown): Data {
  return v && typeof v === "object" ? (v as Data) : {};
}

function safe(url: unknown): string | null {
  const s = str(url);
  return s && /^https?:\/\//i.test(s) ? s : null;
}

function prNumber(url: unknown): number | null {
  const m = /\/(?:pull|pulls|merge_requests)\/(\d+)\/?$/.exec(str(url) ?? "");
  return m ? Number(m[1]) : null;
}

function place(v: unknown): string | null {
  const file = str(obj(v).file);
  const line = num(obj(v).line);
  return file ? (line ? `${file}:${line}` : file) : null;
}

const VERDICT = {
  approved: { icon: "approved", text: "approved" },
  changes_requested: { icon: "changes", text: "requested changes on" },
  commented: { icon: "reviewed", text: "reviewed" },
} as const;

/** The words for a `git.*` entry, or the poll's `pr.merged` / `pr.closed`; null for any other kind. */
export function describeGitEvent(kind: string, data: Data): GitLine | null {
  if (kind === "pr.merged" || kind === "pr.closed") {
    const n = prNumber(data.url);
    const what = n ? `PR #${n}` : "The pull request";
    return {
      icon: kind === "pr.merged" ? "merged" : "closed", lead: null, agent: false, login: null, host: null,
      text: kind === "pr.merged" ? `${what} merged` : `${what} closed without merging`,
      href: safe(data.url), quote: null, where: null, detail: null,
    };
  }
  if (!kind.startsWith("git.")) return null;
  const actor = data.actor ? obj(data.actor) : null;
  const pr = data.pr ? obj(data.pr) : null;
  const prRef = pr && num(pr.number) ? `PR #${num(pr.number)}` : "the pull request";
  const prUrl = safe(pr?.url);
  const base: GitLine = {
    icon: "push", lead: str(actor?.name), agent: actor?.kind === "agent", login: str(actor?.login), text: "",
    host: HOST_NAME[data.host as GitKind] ?? null, href: prUrl, quote: null, where: null, detail: null,
  };
  switch (kind) {
    case "git.pushed": {
      const n = num(data.commits) ?? 0;
      const updated = pr && num(pr.number) ? ` · PR #${num(pr.number)} updated` : "";
      const titles = Array.isArray(data.titles) ? data.titles : [];
      return {
        ...base, text: `pushed ${n} commit${n === 1 ? "" : "s"} to ${str(data.branch) ?? "the branch"}${updated}`,
        href: prUrl ?? safe(data.compare_url), quote: str(titles[0]),
      };
    }
    case "git.pr_opened":
      return { ...base, icon: "opened", text: `opened ${prRef} · ${str(data.branch) ?? "?"} → ${str(data.base) ?? "?"}` };
    case "git.commented":
      return { ...base, icon: "comment", text: `commented on ${prRef}`, href: safe(data.url) ?? prUrl, quote: str(data.excerpt), where: place(data) };
    case "git.reviewed": {
      const verdict = VERDICT[data.verdict as keyof typeof VERDICT] ?? VERDICT.commented;
      const first = obj(data.first);
      const count = num(data.comments) ?? 0;
      return {
        ...base, icon: verdict.icon, text: `${verdict.text} ${prRef}`, href: safe(data.url) ?? prUrl,
        quote: str(data.excerpt) ?? str(first.excerpt), where: place(first),
        detail: count ? `${count} comment${count === 1 ? "" : "s"}` : null,
      };
    }
    case "git.checks": {
      const passed = data.result === "passed";
      return { ...base, icon: passed ? "checks-passed" : "checks-failed", lead: null, agent: false, text: `Checks ${passed ? "passed" : "failed"} on ${prRef}` };
    }
    case "git.pr_merged":
      return { ...base, icon: "merged", text: `merged ${prRef}` };
    case "git.pr_closed":
      return { ...base, icon: "closed", text: `closed ${prRef} without merging` };
    default:
      return null;
  }
}
