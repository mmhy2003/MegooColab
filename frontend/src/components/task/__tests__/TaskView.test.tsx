import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TaskView } from "@/components/task/TaskView";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/projects/PAY/tasks/1",
  useSearchParams: () => new URLSearchParams(),
}));

const TASK = {
  id: "t1", key: "PAY-1", number: 1, project_id: "p1", type: "task", title: "Fix login", description_md: "",
  column_id: "c1", column_category: "before", position: 1, priority: "medium", story_points: null, due_date: null,
  assignee_user_id: null, assignee_agent_id: null, assignee_agent: null, reporter_id: "u2", parent_id: null,
  sprint_id: null, completed_at: null, created_at: "2026-10-29T00:00:00Z", updated_at: "2026-10-29T00:00:00Z",
  labels: [], subtask_count: 0, subtask_done_count: 0, links: [], watcher_ids: [], workflow: null, waiting_on: [],
  pull_request: null, branch_from: null, start_branch: null, back_merge_into: null, branch_from_locked: false,
};

function show(expanded?: boolean, task: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body =
        url === "/api/auth/me" ? { user: { id: "u1", name: "Mona", email: "m@x.io", role: "member", status: "active" } }
        : url === "/api/tasks/PAY-1" ? { ...TASK, ...task }
        : url === "/api/projects/PAY" ? { id: "p1", key: "PAY", name: "Pay", status: "active", sprints_enabled: false, team_ids: [] }
        : url === "/api/projects/PAY/columns" ? [{ id: "c1", name: "To Do", category: "before", position: 0 }]
        : url === "/api/users" ? [{ id: "u1", name: "Mona", email: "m@x.io", role: "member", status: "active" }]
        : url.endsWith("/records") ? { decisions: [], test_runs: [], unverified_steps: [] }
        : url.startsWith("/api/tasks/PAY-1/workflow") ? null
        : [];
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TaskView taskKey="PAY-1" onOpenTask={() => {}} onDeleted={() => {}} expanded={expanded} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const CENTRED = "md:px-[max(1rem,calc((100%_-_80rem)/2_+_1rem))]";

describe("TaskView expanded", () => {
  it("keeps the header and the task, details beside it, to a centred area up to 80rem wide", async () => {
    show(true);
    await screen.findByText("Fix login");
    expect(document.querySelector("header")).toHaveClass(CENTRED);
    expect(document.querySelector("[data-task-scroll]")).toHaveClass(CENTRED, "lg:grid-cols-[minmax(0,1fr)_20rem]");
  });

  it("uses the card's own width otherwise", async () => {
    show();
    await screen.findByText("Fix login");
    expect(document.querySelector("header")).not.toHaveClass(CENTRED);
    expect(document.querySelector("[data-task-scroll]")).not.toHaveClass(CENTRED);
  });
});

describe("TaskView in one column (a phone, a narrow window)", () => {
  beforeEach(() => window.localStorage.clear());
  const details = () => document.querySelector("[data-task-details]") as HTMLElement;

  it("puts the details and the workflow first, so Activity and the comment box come last", async () => {
    show();
    await screen.findByText("Fix login");
    const aside = document.querySelector("aside")!;
    expect(aside).toHaveClass("max-lg:order-first");
    // the workflow comes after the folded details there; beside the task (lg) the order is as before
    expect(document.querySelector("[data-task-workflow]")).toHaveClass("max-lg:order-last");
  });

  it("folds the details to a line of what matters, which opens the full list, and remembers it", async () => {
    show(false, { due_date: "2026-12-01", assignee_user_id: "u1" });
    const toggle = await screen.findByRole("button", { name: "Show all details" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle.closest("[data-details-summary]")).toHaveClass("lg:hidden");
    const chips = document.querySelector("[data-details-summary] ul")!;
    expect(chips).toHaveTextContent("To Do");
    expect(chips).toHaveTextContent("Mona");
    expect(chips).toHaveTextContent("medium");
    expect(chips).toHaveTextContent("Due");
    expect(details()).toHaveClass("max-lg:hidden");
    await userEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Hide details" })).toHaveAttribute("aria-expanded", "true");
    expect(details()).not.toHaveClass("max-lg:hidden");
    expect(window.localStorage.getItem("tasks.detailsOpen")).toBe("true");
  });

  it("says Unassigned when nobody has the task", async () => {
    show();
    await screen.findByRole("button", { name: "Show all details" });
    expect(document.querySelector("[data-details-summary] ul")).toHaveTextContent("Unassigned");
  });
});
