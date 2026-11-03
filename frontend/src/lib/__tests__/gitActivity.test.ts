import { describe, expect, it } from "vitest";

import { describeGitEvent } from "@/lib/gitActivity";

const PR = { number: 42, url: "https://github.com/acme/pay/pull/42" };
const mo = { kind: "person", name: "mo", login: "mo" };
const agent = { kind: "agent", agent_id: "a1", name: "laptop-claude", login: "mo" };

describe("describeGitEvent", () => {
  it("words each kind as the Activity shows it", () => {
    const line = (kind: string, data: Record<string, unknown>) => describeGitEvent(kind, { host: "github", actor: mo, pr: PR, ...data });
    expect(line("git.pushed", { pr: null, branch: "megoo/PAY-7-retries", commits: 1, titles: ["fix: back off"] })).toMatchObject({
      icon: "push", lead: "mo", text: "pushed 1 commit to megoo/PAY-7-retries", host: "GitHub", quote: "fix: back off",
    });
    expect(line("git.pushed", { branch: "megoo/PAY-7-retries", commits: 2, titles: [] })?.text).toBe(
      "pushed 2 commits to megoo/PAY-7-retries · PR #42 updated",
    );
    expect(line("git.pr_opened", { branch: "megoo/PAY-7-retries", base: "main", title: "Retries" })).toMatchObject({
      icon: "opened", text: "opened PR #42 · megoo/PAY-7-retries → main", href: PR.url,
    });
    expect(line("git.commented", { excerpt: "Looks good", url: "https://github.com/c/1", file: "src/a.py", line: 9 })).toMatchObject({
      icon: "comment", text: "commented on PR #42", quote: "Looks good", where: "src/a.py:9", href: "https://github.com/c/1",
    });
    const review = (verdict: string) => line("git.reviewed", { verdict, excerpt: "Two things", url: "https://github.com/r/9", comments: 2,
      first: { file: "src/a.py", line: 88, excerpt: "Add a delay" } });
    // a summary is quoted alone; the place goes with the line comment's own words
    expect(review("approved")).toMatchObject({ icon: "approved", text: "approved PR #42", quote: "Two things", where: null, detail: "2 comments" });
    expect(review("changes_requested")).toMatchObject({ icon: "changes", text: "requested changes on PR #42" });
    expect(review("commented")).toMatchObject({ icon: "reviewed", text: "reviewed PR #42" });
    expect(line("git.reviewed", { verdict: "commented", excerpt: "", comments: 1, first: { file: "a", line: 1, excerpt: "Only this" } })).toMatchObject({
      quote: "Only this", where: "a:1",
    });
    expect(line("git.checks", { actor: null, result: "passed" })).toMatchObject({ icon: "checks-passed", lead: null, text: "Checks passed on PR #42" });
    expect(line("git.checks", { actor: null, result: "failed" })).toMatchObject({ icon: "checks-failed", text: "Checks failed on PR #42" });
    expect(line("git.pr_merged", {})).toMatchObject({ icon: "merged", lead: "mo", text: "merged PR #42" });
    expect(line("git.pr_closed", {})).toMatchObject({ icon: "closed", text: "closed PR #42 without merging" });
  });

  it("the poll's nameless merge and close", () => {
    expect(describeGitEvent("pr.merged", { url: PR.url })).toMatchObject({ icon: "merged", lead: null, text: "PR #42 merged", href: PR.url });
    expect(describeGitEvent("pr.closed", { url: "https://x/y" })).toMatchObject({ text: "The pull request closed without merging" });
  });

  it("an agent gets its tag and keeps the host login", () => {
    expect(describeGitEvent("git.pushed", { host: "gitlab", actor: agent, pr: null, branch: "b", commits: 1, titles: [] })).toMatchObject({
      lead: "laptop-claude", agent: true, login: "mo", host: "GitLab",
    });
    expect(describeGitEvent("git.pr_merged", { host: "github", actor: mo, pr: PR })?.agent).toBe(false);
  });

  it("never links anything but http(s), and knows nothing of other kinds", () => {
    expect(describeGitEvent("git.pr_merged", { host: "github", actor: mo, pr: { number: 1, url: "javascript:alert(1)" } })?.href).toBeNull();
    expect(describeGitEvent("git.x", {})).toBeNull();
    expect(describeGitEvent("created", {})).toBeNull();
  });
});
