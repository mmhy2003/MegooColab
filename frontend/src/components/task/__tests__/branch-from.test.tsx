import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TaskCardView } from "@/components/board/TaskCard";
import { TaskFields } from "@/components/task/TaskFields";
import type { Task } from "@/lib/types";

const base = {
  id: "t1", key: "PAY-1", type: "bug", column_id: "c1", priority: "medium", story_points: null, due_date: null,
  assignee_user_id: null, assignee_agent_id: null, assignee_agent: null, parent_id: null, sprint_id: null, labels: [],
  watcher_ids: [], branch_from: null, start_branch: null, back_merge_into: null, branch_from_locked: false,
} as unknown as Task;

function setup(extra: Partial<Task> = {}, defaultBranch: string | null = "develop") {
  const onPatch = vi.fn();
  render(
    <TaskFields task={{ ...base, ...extra } as Task} columns={[]} users={[]} labels={[]} parents={[]} sprints={undefined}
      meId="u1" disabled={false} defaultBranch={defaultBranch}
      onPatch={onPatch} onMove={vi.fn()} onSprint={vi.fn()} onWatch={vi.fn()} />,
  );
  return onPatch;
}
const field = () => screen.getByRole("textbox", { name: "Branch from" });

describe("Branch from field", () => {
  it("shows the default branch as its placeholder", () => {
    setup();
    expect(field()).toHaveAttribute("placeholder", "develop (default)");
  });

  it("says Default branch when the project has no single repository", () => {
    setup({}, null);
    expect(field()).toHaveAttribute("placeholder", "Default branch");
  });

  it("patches the branch on blur, and null when cleared", async () => {
    const onPatch = setup();
    await userEvent.type(field(), "main");
    await userEvent.tab();
    expect(onPatch).toHaveBeenLastCalledWith({ branch_from: "main" });
  });

  it("clears to null", async () => {
    const onPatch = setup({ branch_from: "main" } as Partial<Task>);
    await userEvent.clear(field());
    await userEvent.tab();
    expect(onPatch).toHaveBeenLastCalledWith({ branch_from: null });
  });

  it("is read-only once work started from a branch", () => {
    setup({ branch_from: "main", start_branch: "main", branch_from_locked: true } as Partial<Task>);
    expect(field()).toHaveAttribute("readonly");
    expect(screen.getByText("Locked: work started from main.")).toBeInTheDocument();
  });

  it("is read-only once a connect-only workflow started", () => {
    setup({ branch_from_locked: true } as Partial<Task>);
    expect(screen.getByText("Locked: the workflow has started.")).toBeInTheDocument();
  });
});

describe("Board card", () => {
  it("shows where a production fix starts", () => {
    render(<TaskCardView task={{ ...base, branch_from: "main" } as Task} />);
    const badge = screen.getByText("from main");
    expect(badge).toHaveAttribute("title", "Starts from main instead of the default branch");
  });

  it("hides the badge when it turned out to be the default branch", () => {
    render(<TaskCardView task={{ ...base, branch_from: "develop", start_branch: "develop" } as Task} />);
    expect(screen.queryByText("from develop")).toBeNull();
  });
});
