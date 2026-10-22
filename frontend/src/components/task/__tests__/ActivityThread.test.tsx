import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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
