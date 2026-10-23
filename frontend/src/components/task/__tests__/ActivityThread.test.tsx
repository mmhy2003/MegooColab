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
      ["agent_run_failed", { reason: "runner_disconnected" }, "failed: runner_disconnected"],
      ["agent_run_cancelled", {}, "was cancelled"],
    ];
    for (const [kind, data, text] of cases) {
      const { unmount } = render1(agentEvent("x", kind, data));
      expect(screen.getByRole("listitem").textContent).toContain(text);
      unmount();
    }
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
