import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ActivityThread } from "@/components/task/ActivityThread";
import type { ActivityItem } from "@/lib/types";

const PR = { number: 42, url: "https://github.com/acme/pay/pull/42" };
const mo = { kind: "person", name: "mo", login: "mo" };
const agent = { kind: "agent", agent_id: "a1", name: "laptop-claude", login: "mo" };
const ev = (id: string, kind: string, data: Record<string, unknown>): ActivityItem => ({
  type: "event", id, at: "2026-11-03T10:00:00Z", actor: null, kind, data: { host: "github", pr: PR, ...data },
});

const items: ActivityItem[] = [
  ev("e1", "git.pushed", { actor: agent, pr: null, branch: "megoo/PAY-7-retries", commits: 1, titles: ["fix: back off"] }),
  ev("e2", "git.pr_opened", { actor: agent, branch: "megoo/PAY-7-retries", base: "main", title: "Retries" }),
  ev("e3", "git.reviewed", { actor: { ...mo, name: "rev", login: "rev" }, verdict: "changes_requested", excerpt: "<script>alert(1)</script>",
    url: "https://github.com/r/9", comments: 2, first: { file: "src/a.py", line: 88, excerpt: "Add a delay" } }),
  ev("e4", "git.checks", { actor: null, result: "passed" }),
  ev("e5", "git.pr_merged", { actor: mo }),
];

describe("ActivityThread: the pull request's events", () => {
  it("shows who, what, where and the host", () => {
    render(<ActivityThread items={items} columnNames={new Map()} userNames={new Map()} />);
    const rows = screen.getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("laptop-claude");
    expect(rows[0]).toHaveTextContent("pushed 1 commit to megoo/PAY-7-retries");
    expect(within(rows[0]).getByText("agent")).toBeInTheDocument();
    expect(within(rows[0]).getByText("GitHub")).toBeInTheDocument();
    expect(within(rows[0]).getByText("laptop-claude")).toHaveAttribute("title", "mo on GitHub");
    expect(rows[1]).toHaveTextContent("opened PR #42 · megoo/PAY-7-retries → main");
    expect(rows[2]).toHaveTextContent("rev requested changes on PR #42");
    expect(rows[2]).toHaveTextContent("src/a.py:88");
    expect(rows[2]).toHaveTextContent("2 comments");
    expect(within(rows[2]).getByText("<script>alert(1)</script>")).toBeInTheDocument();
    expect(within(rows[2]).queryByText("agent")).toBeNull();
    expect(rows[3]).toHaveTextContent("Checks passed on PR #42");
    expect(rows[3]).not.toHaveTextContent("Someone");
    expect(rows[4]).toHaveTextContent("mo merged PR #42");
    const link = within(rows[4]).getByRole("link", { name: /merged PR #42/ });
    expect(link).toHaveAttribute("href", PR.url);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("the poll's nameless merge reads as its own sentence", () => {
    render(<ActivityThread items={[{ type: "event", id: "p", at: "2026-11-03T10:00:00Z", actor: null, kind: "pr.merged", data: { url: PR.url } }]}
      columnNames={new Map()} userNames={new Map()} />);
    expect(screen.getByRole("listitem")).toHaveTextContent("PR #42 merged");
    expect(screen.getByRole("listitem")).not.toHaveTextContent("Someone");
  });
});
