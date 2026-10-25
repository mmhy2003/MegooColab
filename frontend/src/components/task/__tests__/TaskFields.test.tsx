import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TaskFields } from "@/components/task/TaskFields";
import type { ProjectAgent, Task, User } from "@/lib/types";

const task = {
  id: "t1", key: "PAY-1", type: "task", column_id: "c1", priority: "medium", story_points: null, due_date: null,
  assignee_user_id: null, assignee_agent_id: "a1", assignee_agent: { id: "a1", name: "Ann's Codex", program: "codex", owner_id: "u1", status: "online" },
  parent_id: null, sprint_id: null, labels: [], watcher_ids: [],
} as unknown as Task;
const users = [{ id: "u2", name: "Sara Kim", status: "active" }] as unknown as User[];
const agents = [{ id: "a1", name: "Ann's Codex", can_use: true }, { id: "a2", name: "Bob's Codex", can_use: false }] as unknown as ProjectAgent[];

function setup() {
  const onPatch = vi.fn();
  render(
    <TaskFields task={task} columns={[]} users={users} agents={agents} labels={[]} parents={[]} sprints={undefined} meId="u1" disabled={false}
      onPatch={onPatch} onMove={vi.fn()} onSprint={vi.fn()} onWatch={vi.fn()} />,
  );
  return onPatch;
}
const pick = (value: string) => fireEvent.change(screen.getByLabelText("Assignee"), { target: { value } });

describe("TaskFields assignee", () => {
  it("patches an agent, a user, and both-null for Unassigned", () => {
    const onPatch = setup();
    pick("agent:a1");
    expect(onPatch).toHaveBeenLastCalledWith({ assignee_agent_id: "a1" });
    pick("user:u2");
    expect(onPatch).toHaveBeenLastCalledWith({ assignee_user_id: "u2" });
    pick("");
    expect(onPatch).toHaveBeenLastCalledWith({ assignee_user_id: null, assignee_agent_id: null });
  });

  it("shows the full name of the chosen assignee on hover", () => {
    setup();
    expect(screen.getByLabelText("Assignee")).toHaveAttribute("title", "Ann's Codex");
  });

  it("lists agents the caller cannot use as disabled", () => {
    setup();
    expect(screen.getByRole("option", { name: "Bob's Codex" })).toBeDisabled();
  });
});
