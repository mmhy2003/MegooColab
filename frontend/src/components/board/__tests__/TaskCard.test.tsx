import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TaskCardView } from "@/components/board/TaskCard";
import type { Task } from "@/lib/types";

const task: Task = {
  id: "t1",
  key: "PAY-12",
  number: 12,
  project_id: "p1",
  type: "story",
  title: "Sync orders with ERP",
  description_md: "",
  column_id: "c1",
  column_category: "working",
  position: 1024,
  priority: "high",
  story_points: 5,
  due_date: null,
  assignee_user_id: "u1",
  assignee_agent_id: null,
  reporter_id: "u1",
  parent_id: null,
  sprint_id: null,
  completed_at: null,
  created_at: "2026-10-22T00:00:00Z",
  updated_at: "2026-10-22T00:00:00Z",
  labels: [{ id: "l1", name: "backend", color: "#05D9E8" }],
  subtask_count: 5,
  subtask_done_count: 2,
  links: [],
  watcher_ids: [],
};

describe("TaskCardView", () => {
  it("shows key, title, points, labels, assignee and subtask progress", () => {
    render(<TaskCardView task={task} assigneeName="Ahmed Ali" />);
    expect(screen.getByText("PAY-12")).toBeInTheDocument();
    expect(screen.getByText("Sync orders with ERP")).toBeInTheDocument();
    expect(screen.getByLabelText("5 story points")).toBeInTheDocument();
    expect(screen.getByText("backend")).toBeInTheDocument();
    expect(screen.getByLabelText("2 of 5 subtasks done")).toHaveTextContent("2/5");
    expect(screen.getByTitle("Assigned to Ahmed Ali")).toBeInTheDocument();
    expect(screen.getByLabelText("Priority: high")).toBeInTheDocument();
  });

  it("highlights the card being dragged", () => {
    const { container, rerender } = render(<TaskCardView task={task} />);
    expect(container.firstElementChild).not.toHaveClass("glow-box");
    rerender(<TaskCardView task={task} dragging />);
    expect(container.firstElementChild).toHaveClass("glow-box");
  });

  it("omits subtask progress when there are none", () => {
    render(<TaskCardView task={{ ...task, subtask_count: 0, subtask_done_count: 0 }} />);
    expect(screen.queryByLabelText(/subtasks done/)).not.toBeInTheDocument();
  });

  it("shows a bot avatar and status for an agent assignee", () => {
    const agent = { id: "a1", name: "Ann's Codex", program: "codex", owner_id: "u1", status: "busy" };
    render(<TaskCardView task={{ ...task, assignee_user_id: null, assignee_agent_id: "a1", assignee_agent: agent }} />);
    expect(screen.getByRole("img", { name: "Agent Ann's Codex" })).toBeInTheDocument();
    expect(screen.getByText("Busy")).toBeInTheDocument();
  });

  const wf = {
    driver: "runner", stage: "plan", status: "waiting_human", needs: "plan_approval", enforcement: "enforced",
    current_step: null, steps_total: null, escalation_reason: null, can_act: true,
  } as const;

  it("shows NEEDS YOU only when can_act", () => {
    const { rerender } = render(<TaskCardView task={{ ...task, workflow: wf }} />);
    expect(screen.getByText("NEEDS YOU")).toHaveAttribute("title", "Approve the plan");
    expect(screen.getByLabelText("Stage: Plan (3 of 6)")).toBeInTheDocument();
    expect(screen.getByText(/waiting for you/)).toBeInTheDocument();
    rerender(<TaskCardView task={{ ...task, workflow: { ...wf, can_act: false } }} />);
    expect(screen.queryByText("NEEDS YOU")).not.toBeInTheDocument();
    expect(screen.queryByText(/for you/i)).not.toBeInTheDocument();
    expect(screen.getByText(/waiting on a person/)).toBeInTheDocument();
  });

  it("shows enforcement chip and build progress", () => {
    const build = { ...wf, stage: "build", status: "running", needs: null, current_step: 2, steps_total: 5 } as const;
    const { rerender } = render(<TaskCardView task={{ ...task, workflow: { ...build, enforcement: "unenforced" } }} />);
    expect(screen.getByText("unenforced")).toHaveAttribute("title");
    expect(screen.getByText("2 of 5 steps")).toBeInTheDocument();
    rerender(<TaskCardView task={{ ...task, workflow: { ...build, enforcement: "partially_enforced" } }} />);
    expect(screen.getByText("partially enforced")).toBeInTheDocument();
    rerender(<TaskCardView task={{ ...task, workflow: build }} />);
    expect(screen.queryByText(/enforced/)).not.toBeInTheDocument();
  });
});
