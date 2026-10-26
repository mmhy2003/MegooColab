import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ActivityThread } from "@/components/task/ActivityThread";
import type { ActivityItem } from "@/lib/types";

const actor = {
  id: "u1",
  email: "a@x.io",
  name: "Ahmed Ali",
  role: "member" as const,
  status: "active" as const,
  must_change_password: false,
  totp_enabled: false,
};

const items: ActivityItem[] = [
  { type: "event", id: "e1", at: "2026-10-22T10:00:00Z", actor, kind: "created", data: {} },
  { type: "comment", id: "c1", at: "2026-10-22T10:01:00Z", actor, body_md: "Looks **good**", edited_at: null },
  { type: "event", id: "e2", at: "2026-10-22T10:02:00Z", actor, kind: "status_changed", data: { from_column: "c1", to_column: "c3", to_category: "review" } },
  { type: "event", id: "e3", at: "2026-10-22T10:03:00Z", actor, kind: "assigned", data: { from: null, to: "u2" } },
  { type: "event", id: "e4", at: "2026-10-22T10:04:00Z", actor, kind: "agent_stage_entered", data: {} },
];

describe("ActivityThread", () => {
  const columnNames = new Map([["c3", "In Review"]]);
  const userNames = new Map([["u2", "Sara Kim"]]);

  it("renders comments and readable events in order", () => {
    render(<ActivityThread items={items} columnNames={columnNames} userNames={userNames} />);
    const rows = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(rows[0]).toContain("Ahmed Ali created this task");
    expect(rows[1]).toContain("Looks good");
    expect(screen.getByText("good").tagName).toBe("STRONG");
    expect(rows[2]).toContain("Ahmed Ali moved this to In Review");
    expect(rows[3]).toContain("Ahmed Ali assigned this to Sara Kim");
    expect(rows[4]).toContain("Ahmed Ali agent_stage_entered");
  });

  it("describes questions to other projects", () => {
    const asked: ActivityItem = { type: "event", id: "e8", at: "2026-10-22T10:07:00Z", actor, kind: "question_asked", data: { question_id: "q1", target_key: "QBB", number: 1 } };
    const answered: ActivityItem = { type: "event", id: "e9", at: "2026-10-22T10:08:00Z", actor, kind: "question_answered", data: { question_id: "q1", target_key: "QBB", number: 1 } };
    render(<ActivityThread items={[asked, answered]} columnNames={columnNames} userNames={userNames} />);
    const rows = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(rows[0]).toContain("Ahmed Ali asked QBB a question (Q1)");
    expect(rows[1]).toContain("QBB answered Q1");
    expect(rows[1]).not.toContain("Ahmed Ali");
  });

  it("says an agent was assigned, not that the task was unassigned", () => {
    const toAgent: ActivityItem = { type: "event", id: "e7", at: "2026-10-22T10:06:00Z", actor, kind: "assigned", data: { from: null, to: null, to_agent: "a1" } };
    render(<ActivityThread items={[toAgent]} columnNames={columnNames} userNames={userNames} agentNames={new Map([["a1", "Ahmed's Claude Code"]])} />);
    expect(screen.getByRole("listitem").textContent).toContain("Ahmed Ali assigned this to Ahmed's Claude Code");
  });

  it("never renders raw HTML from comments", () => {
    const evil: ActivityItem = { type: "comment", id: "c9", at: "2026-10-22T10:05:00Z", actor, body_md: "<script>alert(1)</script><b>bold</b>", edited_at: null };
    const { container } = render(<ActivityThread items={[evil]} columnNames={columnNames} userNames={userNames} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });

  it("marks edited comments", () => {
    const edited: ActivityItem = { ...items[1], id: "c2", edited_at: "2026-10-22T11:00:00Z" };
    render(<ActivityThread items={[edited]} columnNames={columnNames} userNames={userNames} />);
    expect(screen.getByText("(edited)")).toBeInTheDocument();
  });
});

describe("ActivityThread agent events", () => {
  const agentEvent = (id: string, kind: string, data: Record<string, unknown>): ActivityItem => ({
    type: "event",
    id,
    at: "2026-10-22T10:00:00Z",
    actor: null,
    kind,
    data: { agent_id: "a1", run_id: "r1", ...data },
  });
  const render1 = (item: ActivityItem, agentNames = new Map([["a1", "Ann's Codex"]])) =>
    render(<ActivityThread items={[item]} columnNames={new Map()} userNames={new Map()} agentNames={agentNames} />);

  it("renders a file change with the agent's name", () => {
    render1(agentEvent("g1", "agent_file_change", { path: "src/a.ts", lines_added: 3, lines_removed: 1 }));
    expect(screen.getByRole("listitem").textContent).toContain("Ann's Codex changed src/a.ts (+3 −1)");
  });

  it("renders a denied permission", () => {
    render1(agentEvent("g2", "agent_permission", { tool_kind: "edit", title: "Write x.txt", decision: "denied", reason: "read_only" }));
    expect(screen.getByRole("listitem").textContent).toContain("Ann's Codex was denied: Write x.txt");
  });

  it("falls back to Agent when the agent is unknown", () => {
    render1(agentEvent("g3", "agent_run_started", {}), new Map());
    expect(screen.getByRole("listitem").textContent).toContain("Agent started working");
  });

  it("renders agent messages as plain text", () => {
    const { container } = render1(agentEvent("g4", "agent_message", { text: "<b>hi</b> **x**" }));
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByRole("listitem").textContent).toContain("<b>hi</b> **x**");
  });

  it("describes the other agent kinds", () => {
    const cases: [string, Record<string, unknown>, string][] = [
      ["agent_run_queued", {}, "queued a run"],
      ["agent_plan", { entries: [{}, {}] }, "updated the plan (2 steps)"],
      ["agent_tool", { title: "Read a.ts", status: "completed" }, "Read a.ts (completed)"],
      ["agent_command", { command: "pytest", exit_code: 1 }, "ran pytest → exit 1"],
      ["agent_run_completed", { summary: "Done" }, "finished: Done"],
      ["agent_run_failed", { reason: "runner_disconnected" }, "failed: the runner disconnected"],
      ["agent_run_cancelled", {}, "was cancelled"],
      ["agent_run_cancelled", { reason: "runner_unauthorized" }, "was cancelled: the runner's token was revoked"],
    ];
    for (const [kind, data, text] of cases) {
      const { unmount } = render1(agentEvent("x", kind, data));
      expect(screen.getByRole("listitem").textContent).toContain(text);
      unmount();
    }
  });
});

describe("ActivityThread run outcomes", () => {
  const event = (kind: string, data: Record<string, unknown>, who: ActivityItem["actor"] = null): ActivityItem => ({
    type: "event",
    id: "r",
    at: "2026-10-22T10:00:00Z",
    actor: who,
    kind,
    data: { agent_id: "a1", run_id: "r1", ...data },
  });
  const text = (item: ActivityItem) => {
    render(<ActivityThread items={[item]} columnNames={new Map()} userNames={new Map()} agentNames={new Map([["a1", "Ann's Codex"]])} />);
    return screen.getByRole("listitem").textContent ?? "";
  };

  it("says a person cancelled the run, not that they were cancelled", () => {
    const row = text(event("agent_run_cancelled", {}, actor));
    expect(row).toContain("Ahmed Ali cancelled the run");
    expect(row).not.toContain("was cancelled");
  });

  it("drops the exit part of a command without an exit code", () => {
    const row = text(event("agent_command", { command: "pytest", exit_code: null }));
    expect(row).toContain("Ann's Codex ran pytest");
    expect(row).not.toContain("exit");
  });

  it.each([
    ["runner_disconnected", "the runner disconnected"],
    ["runner_unauthorized", "the runner's token was revoked"],
    ["owner_deactivated", "the owner was deactivated"],
    ["user_deactivated", "the owner or requester was deactivated"],
    ["owner_lost_access", "the owner lost access to this project"],
    ["busy", "the agent was busy"],
    ["agent_error", "the agent hit an error"],
    ["not_bound", "the agent isn't set up for this project"],
    ["agent_not_bound", "the agent isn't set up for this project"],
    ["brand_new_code", "brand new code"],
  ])("explains the failure reason %s", (reason, friendly) => {
    expect(text(event("agent_run_failed", { reason }))).toContain(`Ann's Codex failed: ${friendly}`);
  });
});

describe("ActivityThread paging", () => {
  it("offers to load earlier activity when there is more", () => {
    const onLoadEarlier = vi.fn();
    render(<ActivityThread items={[]} columnNames={new Map()} userNames={new Map()} hasMore onLoadEarlier={onLoadEarlier} />);
    fireEvent.click(screen.getByRole("button", { name: "Load earlier activity" }));
    expect(onLoadEarlier).toHaveBeenCalled();
  });

  it("hides the button when everything is loaded", () => {
    render(<ActivityThread items={[]} columnNames={new Map()} userNames={new Map()} />);
    expect(screen.queryByRole("button", { name: "Load earlier activity" })).not.toBeInTheDocument();
  });
});

describe("ActivityThread workflow events", () => {
  const names = { columnNames: new Map([["c3", "Review"]]), userNames: new Map<string, string>() };
  const ev = (id: string, kind: string, data: Record<string, unknown>, withActor = false): ActivityItem => ({
    type: "event", id, at: "2026-10-25T10:00:00Z", actor: withActor ? actor : null, kind, data,
  });
  const rows = (list: ActivityItem[]) => {
    render(<ActivityThread items={list} taskKey="PAY-1" {...names} />);
    return screen.getAllByRole("listitem");
  };

  it("renders an enforcement violation in pink, with text", () => {
    const [row] = rows([ev("v1", "enforcement.violation", { stage: "brainstorm", role: "brainstorm" })]);
    expect(row.textContent).toContain("Enforcement violation during Brainstorm: the repository changed");
    expect(row.className).toContain("text-pink");
  });

  it("uses plain past-tense sentences", () => {
    const list = rows([
      ev("1", "document.submitted", { kind: "design", version: 2 }),
      ev("2", "document.approved", { kind: "plan", version: 1 }, true),
      ev("3", "step.approved", { step: 2 }),
      ev("4", "review.result", { scope: "step", step: 2, round: 1, verdict: "changes_requested", counts: { critical: 0, important: 1, minor: 2 } }),
      ev("5", "status_changed", { to_column: "c3", by: "workflow" }),
      ev("6", "workflow.escalated", { reason: "retries_exhausted" }),
      ev("7", "workflow.paused", { reason: "owner_deactivated" }),
      ev("8", "finish.reported", { outcome: "pull_request", branch: "megoo/PAY-1", pr_url: "javascript:alert(1)" }),
    ]).map((li) => li.textContent);
    expect(list[0]).toContain("The agent submitted design v2");
    expect(list[1]).toContain("Ahmed Ali approved the plan v1");
    expect(list[2]).toContain("Step 2 approved");
    expect(list[3]).toContain("Review of step 2 (round 1): changes requested — 1 important, 2 minor");
    expect(list[4]).toContain("Moved to Review by the workflow");
    expect(list[5]).toContain("The agent's runs failed 3 times in a row.");
    expect(list[6]).toContain("MegooColab paused the workflow (the agent's owner was deactivated)");
    expect(list[7]).toContain("Finish reported: opened a pull request on megoo/PAY-1");
    expect(screen.queryByRole("link", { name: "Open the pull request" })).toBeNull();
  });

  it("says when the board has no column for the workflow's move, and a plain manual pause", () => {
    const list = rows([
      ev("1", "workflow.no_column", { category: "review" }),
      ev("2", "workflow.paused", { reason: "manual" }, true),
    ]).map((li) => li.textContent);
    expect(list[0]).toContain("The board has no review column, so the card stayed where it was");
    expect(list[1]).toContain("Ahmed Ali paused the workflow");
    expect(list[1]).not.toContain("(manual)");
  });

  it("links document events to the document section", () => {
    rows([ev("2", "document.approved", { kind: "plan", version: 1 }, true)]);
    expect(screen.getByRole("link", { name: "plan v1" })).toHaveAttribute("href", "#document-plan-v1");
  });

  it("renders a question item as a card", () => {
    const q: ActivityItem = {
      type: "question", id: "q1", at: "2026-10-25T10:00:00Z", actor: null,
      question: { id: "q1", body: "Which one?", choices: [], status: "withdrawn", mockup: null, answered_by: null, answer_choice: null, answer_text: null },
    };
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ActivityThread items={[q]} taskKey="PAY-1" {...names} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Which one?")).toBeInTheDocument();
    expect(screen.getByText(/withdrawn/)).toBeInTheDocument();
  });
});
