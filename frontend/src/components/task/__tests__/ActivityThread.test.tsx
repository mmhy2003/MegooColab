import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
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
    const followUp: ActivityItem = { type: "event", id: "e10", at: "2026-10-22T10:09:00Z", actor, kind: "question_asked", data: { question_id: "q2", target_key: "QBB", number: 4, follow_up_of_number: 3 } };
    const answered: ActivityItem = { type: "event", id: "e9", at: "2026-10-22T10:08:00Z", actor, kind: "question_answered", data: { question_id: "q1", target_key: "QBB", number: 1 } };
    render(<ActivityThread items={[asked, answered, followUp]} columnNames={columnNames} userNames={userNames} />);
    const rows = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(rows[0]).toContain("Ahmed Ali asked QBB a question (Q1)");
    expect(rows[1]).toContain("QBB answered Q1");
    expect(rows[1]).not.toContain("Ahmed Ali");
    expect(rows[2]).toContain("Ahmed Ali asked QBB a follow-up to Q3 (Q4)");
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

  it("renders an agent's reply as Markdown, never as raw HTML", () => {
    const { container } = render1(agentEvent("g4", "agent_message", { text: "<b>hi</b> **x** and `code`\n\n- one\n- two" }));
    expect(container.querySelector("b")).toBeNull(); // raw HTML is never rendered
    expect(screen.getByText("x").tagName).toBe("STRONG");
    expect(screen.getByText("code").tagName).toBe("CODE");
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(expect.arrayContaining(["one", "two"]));
    // one size below a design or plan, marked as the agent's reply
    const reply = container.querySelector("[data-agent-reply]")!;
    expect(reply).toHaveTextContent("Ann's Codex");
    expect(reply.querySelector(".text-\\[13px\\]")).not.toBeNull();
  });

  it("joins the pieces of one reply into one message", () => {
    const chunks = [
      agentEvent("m1", "agent_message", { text: "two Knowledge Base pages describe a **check" }),
      agentEvent("m2", "agent_message", { text: "_transcript** step and \"Jev\" chec" }),
      agentEvent("m3", "agent_message", { text: "k that the code doesn't have." }),
    ];
    const { container } = render(
      <ActivityThread items={chunks} columnNames={new Map()} userNames={new Map()} agentNames={new Map([["a1", "Ann's Codex"]])} />,
    );
    const replies = container.querySelectorAll("[data-agent-reply]");
    expect(replies).toHaveLength(1);
    expect(replies[0]).toHaveTextContent(`two Knowledge Base pages describe a check_transcript step and "Jev" check that the code doesn't have.`);
    expect(screen.getByText("check_transcript").tagName).toBe("STRONG");
  });

  it("keeps replies apart across other events and other runs", () => {
    const list = [
      agentEvent("m1", "agent_message", { text: "Looking." }),
      agentEvent("t1", "agent_command", { command: "pytest", exit_code: 0 }),
      agentEvent("m2", "agent_message", { text: "Tests pass." }),
      agentEvent("m3", "agent_message", { text: "Next run.", run_id: "r2" }),
    ];
    const { container } = render(
      <ActivityThread items={list} columnNames={new Map()} userNames={new Map()} agentNames={new Map([["a1", "Ann's Codex"]])} />,
    );
    expect([...container.querySelectorAll("[data-agent-reply]")].map((r) => r.textContent)).toEqual([
      expect.stringContaining("Looking."), expect.stringContaining("Tests pass."), expect.stringContaining("Next run."),
    ]);
    // a status line stays a plain line
    expect(screen.getByText(/ran pytest → exit 0/).closest("[data-agent-reply]")).toBeNull();
  });

  it("says a run finished without repeating the reply the summary copies", () => {
    const reply = "I approved step 6 with **no findings**.\n\n- **Tests:** all nine hold\n- `201ea47` changes two files";
    const list = [
      agentEvent("m1", "agent_message", { text: reply.slice(0, 40) }),
      agentEvent("m2", "agent_message", { text: reply.slice(40) }),
      agentEvent("f1", "agent_run_completed", { summary: reply.slice(40) }),
    ];
    const { container } = render(
      <ActivityThread items={list} columnNames={new Map()} userNames={new Map()} agentNames={new Map([["a1", "Ann's Codex"]])} />,
    );
    expect(container.querySelectorAll("[data-agent-reply]")).toHaveLength(1);
    const rows = [...container.querySelectorAll("ol > li")].map((li) => li.textContent ?? "");
    expect(rows[1]).toMatch(/^Ann's Codex finished/);
    expect(rows[1]).not.toContain("Tests");
    expect(container.textContent).not.toContain("**");
    expect(container.textContent).not.toContain("`");
  });

  it("shows a summary that is not in the thread as Markdown under the finished line", () => {
    const { container } = render1(agentEvent("f2", "agent_run_completed", { summary: "Fixed the **timezone** bug in `format_date()`:\n\n- one\n- two" }));
    const row = container.querySelector("ol > li")!;
    expect(row.textContent).toMatch(/^Ann's Codex finished/);
    expect(within(row as HTMLElement).getByText("timezone").tagName).toBe("STRONG");
    expect(within(row as HTMLElement).getByText("format_date()").tagName).toBe("CODE");
    expect(row.querySelector("[data-run-summary]")).not.toBeNull();
    expect(row.textContent).not.toContain("**");
  });

  it("never renders raw HTML from a run's summary", () => {
    const { container } = render1(agentEvent("f3", "agent_run_completed", { summary: "<b>hi</b> <script>x()</script>" }));
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });

  it("checks a summary against the replies of its own run only", () => {
    const list = [
      agentEvent("m1", "agent_message", { text: "Done **here**.", run_id: "r0" }),
      agentEvent("f4", "agent_run_completed", { summary: "Done **here**." }),
    ];
    const { container } = render(
      <ActivityThread items={list} columnNames={new Map()} userNames={new Map()} agentNames={new Map([["a1", "Ann's Codex"]])} />,
    );
    expect(container.querySelector("[data-run-summary]")).not.toBeNull();
  });

  it("links a task the agent created from the chat", () => {
    render1(agentEvent("t1", "agent_task_created", { key: "PAY-42", title: "Retry webhook deliveries", task_id: "t42" }));
    const row = screen.getByRole("listitem");
    expect(row.textContent).toContain("Ann's Codex created PAY-42: Retry webhook deliveries");
    expect(screen.getByRole("link", { name: "PAY-42" })).toHaveAttribute("href", "/projects/PAY/board?task=PAY-42");
  });

  it("describes the other agent kinds", () => {
    const cases: [string, Record<string, unknown>, string][] = [
      ["agent_run_queued", {}, "queued a run"],
      ["agent_plan", { entries: [{}, {}] }, "updated the plan (2 steps)"],
      ["agent_tool", { title: "Read a.ts", status: "completed" }, "Read a.ts (completed)"],
      ["agent_command", { command: "pytest", exit_code: 1 }, "ran pytest → exit 1"],
      ["agent_model", { value: "opus", name: "Opus 4.7" }, "used the model Opus 4.7"],
      ["agent_model", { value: "opus" }, "used the model opus"],
      ["agent_model", { value: "opus", name: "Opus 5.5", effort: "high", effort_name: "High" }, "used the model Opus 5.5 with High effort"],
      ["agent_model", { value: "opus", name: "Opus 5.5", effort: "default", effort_name: "Default" }, "used the model Opus 5.5 with its default effort"],
      ["agent_run_failed", { reason: "effort_unavailable" }, "failed: the effort chosen for this agent isn't available for its model — pick another on My agents"],
      ["agent_run_failed", { reason: "model_unavailable" }, "failed: the model chosen for this agent isn't available — pick another on My agents"],
      ["agent_run_completed", {}, "Ann's Codex finished"],
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

  it("tells of shown mockups and recorded decisions as sentences of their own", () => {
    const list = rows([
      ev("m", "mockup.shown", { version: 3, title: "Settings" }),
      ev("d", "decision.recorded", { step: 2, stage: "build", decision: "Used a map" }),
      ev("f", "decision.recorded", { step: null, stage: "done", decision: "Merged into develop" }),
    ]).map((li) => li.textContent);
    expect(list[0]).toContain("Mockup v3 shown: Settings");
    expect(list[0]).not.toContain("The agent");
    expect(list[1]).toContain("Decision on step 2: Used a map");
    expect(list[2]).toContain("Decision during Done: Merged into develop");
  });

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

  describe("messages for the agent", () => {
    const message = (to_agent: ActivityItem["to_agent"]): ActivityItem[] => [
      { type: "comment", id: "m1", at: "2026-10-22T10:05:00Z", actor: { ...actor, name: "Mo" }, body_md: "Use RetryPolicy", edited_at: null, to_agent },
    ];
    const base = { agent_id: "a1", agent_name: "laptop-claude", stage: null, error: null, delivered_at: null };
    const columnNames = new Map<string, string>();
    const userNames = new Map<string, string>();

    it.each([
      [{ ...base, state: "waiting" as const }, "waiting: goes to its next run"],
      [{ ...base, state: "waiting" as const, error: "boom" }, "couldn't be delivered (boom): goes to its next run"],
      [{ ...base, state: "sending" as const }, "sending…"],
      [{ ...base, state: "read_while_working" as const }, "read while working"],
      [{ ...base, state: "given_at_start" as const, stage: "plan" }, "given at the start of the plan run"],
    ])("shows %o as %s", (toAgent, text) => {
      render(<ActivityThread items={message(toAgent)} columnNames={columnNames} userNames={userNames} />);
      const row = screen.getByRole("listitem");
      expect(row.textContent).toContain("Mo → laptop-claude");
      expect(row.textContent).toContain(text);
      expect(row.textContent).toContain("Use RetryPolicy");
      expect(row.querySelector("[data-agent-message]")).not.toBeNull();
    });

    it("an ordinary comment has no agent heading", () => {
      render(<ActivityThread items={items} columnNames={columnNames} userNames={userNames} />);
      expect(screen.queryByText(/→/)).toBeNull();
    });
  });

  describe("images", () => {
    const img = (id: string, filename: string) => ({ id, filename, size: 1024 });

    it("shows a comment's images with it, and marks each item so it can be linked to", () => {
      const withImages: ActivityItem[] = [
        { type: "comment", id: "c9", at: "2026-10-22T10:01:00Z", actor, body_md: "See these", edited_at: null,
          images: [img("i1", "one.png"), img("i2", "two.png")] },
      ];
      const { container } = render(<ActivityThread items={withImages} columnNames={new Map()} userNames={new Map()} />);
      expect(screen.getByRole("button", { name: "Open one.png" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Open two.png" })).toBeInTheDocument();
      expect(container.querySelector("#activity-c9")).not.toBeNull();
    });

    it("shows a change request's images under it", () => {
      const rejected: ActivityItem[] = [
        { type: "event", id: "e9", at: "2026-10-22T10:01:00Z", actor, kind: "document.rejected",
          data: { kind: "design", version: 1, comment: "like this", document_id: "d1" }, images: [img("i3", "like.png")] },
      ];
      render(<ActivityThread items={rejected} columnNames={new Map()} userNames={new Map()} />);
      expect(screen.getByRole("button", { name: "Open like.png" })).toBeInTheDocument();
    });

    it("shows an answer's images with the answer", () => {
      const answered: ActivityItem[] = [
        { type: "question", id: "q9", at: "2026-10-22T10:01:00Z", actor: null, images: [img("i4", "this.png")],
          question: { id: "q9", body: "Which one?", choices: [], status: "answered", mockup: null,
                      answered_by: { id: "u1", name: "Ahmed Ali" }, answer_choice: null, answer_text: "this" } },
      ];
      render(
        <QueryClientProvider client={new QueryClient()}>
          <ActivityThread items={answered} columnNames={new Map()} userNames={new Map()} taskKey="PAY-1" />
        </QueryClientProvider>,
      );
      expect(screen.getByRole("button", { name: "Open this.png" })).toBeInTheDocument();
    });
  });
});

describe("ActivityThread: a task sent back by its pull request", () => {
  const at = "2026-11-03T10:00:00Z";
  it("words the send-back, the fix and the stop", () => {
    const rows: ActivityItem[] = [
      { type: "event", id: "s1", at, actor: null, kind: "pr.sent_back",
        data: { pr_number: 42, by: "rev", kind: "review", round: 2, of: 3, excerpt: "Two things" } },
      { type: "event", id: "s2", at, actor: null, kind: "pr.sent_back",
        data: { pr_number: 42, by: "mo", kind: "fix_comment", round: 3, of: 3, excerpt: "/fix the timeout" } },
      { type: "event", id: "s3", at, actor: null, kind: "pr.fix_pushed",
        data: { pr_number: 42, round: 2, of: 3, summary: "Added a **back-off** to `retry` <b>x</b>" } },
      { type: "event", id: "s4", at, actor, kind: "pr.send_back_cancelled", data: {} },
    ];
    const { container } = render(<ActivityThread items={rows} columnNames={new Map()} userNames={new Map()} />);
    const text = [...container.querySelectorAll("ol > li")].map((li) => li.textContent);
    expect(text[0]).toContain("Sent back to its agent: changes requested on PR #42 by rev (round 2 of 3)");
    expect(text[1]).toContain("Sent back to its agent: /fix on PR #42 by mo (round 3 of 3)");
    expect(text[2]).toContain("Fixed and pushed to PR #42 (round 2 of 3)");
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText("back-off").tagName).toBe("STRONG");
    expect(screen.getByText("retry").tagName).toBe("CODE");
    expect(text[2]).not.toContain("**");
    expect(text[3]).toContain("Ahmed Ali stopped the fix: back to waiting for the merge");
    expect(text[0]).not.toContain("Someone");
  });
});

describe("ActivityThread: the agent's review of the pull request", () => {
  const at = "2026-11-03T11:00:00Z";
  const reviewed = (data: Record<string, unknown>): ActivityItem => ({
    type: "event", id: String(Math.random()), at, actor: null, kind: "pr.agent_reviewed",
    data: { pr_number: 42, agent_name: "review-bot", agent_id: "a9", summary: "Two <b>things</b>", findings: 3, ...data },
  });
  it("says what the reviewer decided, led by the agent with its tag", () => {
    render(<ActivityThread columnNames={new Map()} userNames={new Map()} items={[
      reviewed({ verdict: "approved", merged: true }),
      reviewed({ verdict: "approved", merged: false, merge_error: "Required review missing" }),
      reviewed({ verdict: "changes_requested", merged: false }),
    ]} />);
    const rows = screen.getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("review-bot");
    expect(within(rows[0]).getByText("agent")).toBeInTheDocument();
    expect(rows[0]).toHaveTextContent("approved PR #42 and merged it");
    expect(rows[1]).toHaveTextContent("approved PR #42 (not merged: Required review missing)");
    expect(rows[2]).toHaveTextContent("requested changes on PR #42 · 3 findings");
    expect(within(rows[2]).getByText("Two <b>things</b>")).toBeInTheDocument();
    expect(rows[2]).not.toHaveTextContent("Someone");
  });
});
