import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
const assignee = () => screen.getByRole("combobox", { name: "Assignee" });

async function pick(name: string) {
  await userEvent.click(assignee());
  await userEvent.click(screen.getByRole("option", { name }));
}

describe("TaskFields assignee", () => {
  it("patches an agent, a user, and both-null for Unassigned", async () => {
    const onPatch = setup();
    await pick("Ann's Codex");
    expect(onPatch).toHaveBeenLastCalledWith({ assignee_agent_id: "a1" });
    await pick("Sara Kim");
    expect(onPatch).toHaveBeenLastCalledWith({ assignee_user_id: "u2" });
    await pick("Unassigned");
    expect(onPatch).toHaveBeenLastCalledWith({ assignee_user_id: null, assignee_agent_id: null });
  });

  it("shows the chosen assignee's name", () => {
    setup();
    expect(assignee()).toHaveTextContent("Ann's Codex");
  });

  it("lists agents the caller cannot use as disabled", async () => {
    setup();
    await userEvent.click(assignee());
    expect(screen.getByRole("option", { name: "Bob's Codex" })).toHaveAttribute("aria-disabled", "true");
  });

  it("filters as you type, without blurring the page", async () => {
    setup();
    await userEvent.click(assignee());
    await userEvent.keyboard("sar");
    expect(screen.getByRole("option", { name: "Sara Kim" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Ann's Codex" })).toBeNull();
    expect(document.querySelector("[data-backdrop]")).toBeNull();
  });

  it("escape closes only the picker, not the task drawer around it", async () => {
    const drawerEscape = vi.fn();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && drawerEscape();
    window.addEventListener("keydown", onKey); // what TaskDrawer listens to
    try {
      setup();
      await userEvent.click(assignee());
      expect(screen.getByRole("listbox")).toBeInTheDocument();
      await userEvent.keyboard("{Escape}");
      expect(screen.queryByRole("listbox")).toBeNull();
      expect(drawerEscape).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener("keydown", onKey);
    }
  });
});
