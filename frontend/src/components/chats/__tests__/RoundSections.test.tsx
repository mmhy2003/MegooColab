import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/chats/c1",
  useSearchParams: () => new URLSearchParams(),
}));

import { RoundSections } from "@/components/chats/RoundSections";
import { chat } from "@/components/chats/__tests__/fixtures";

const TASK = { id: "t7", key: "PAY-7", title: "Fix empty email", type: "task", subtask_count: 2, subtask_done_count: 1 };
const SUBTASKS = [
  { id: "s1", key: "PAY-8", title: "Validate the email", type: "subtask", parent_id: "t7", column_category: "done" },
  { id: "s2", key: "PAY-9", title: "Show the error", type: "subtask", parent_id: "t7", column_category: "todo" },
];
const DESIGN = { kind: "design", status: "awaiting_approval", version: 1 };

/** The round's task with what it holds; empty means a round with nothing but its conversation. */
function show({ latest, empty = false }: { latest: boolean; empty?: boolean }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body =
        url === "/api/tasks/PAY-7" ? { ...TASK, ...(empty ? { subtask_count: 0, subtask_done_count: 0 } : {}) }
        : url.startsWith("/api/projects/PAY/tasks") ? (empty ? [] : SUBTASKS)
        : url === "/api/tasks/PAY-7/workflow" ? { documents: empty ? [] : [DESIGN], can_act: true }
        : url === "/api/tasks/PAY-7/records" ? { decisions: [] }
        : url === "/api/tasks/PAY-7/attachments" ? (empty ? [] : [{ id: "a1", task_id: "t7", filename: "notes.txt", content_type: "text/plain", size: 4, uploaded_by: null, created_at: "2026-11-01T10:00:00Z", image: false, message_kind: null, message_id: null }])
        : [];
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
  const c = chat();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RoundSections chat={c} round={c.rounds[0]} latest={latest} />
    </QueryClientProvider>,
  );
}

const headings = () => screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("RoundSections", () => {
  it("shows a round as a task shows itself: its parts in the task's order, the conversation last", async () => {
    show({ latest: true });
    expect(await screen.findByText("Validate the email")).toBeInTheDocument();
    await screen.findByText("notes.txt");
    expect(headings()).toEqual(["Subtasks (1/2)", "Design", "Questions to other projects", "Attachments", "Activity"]);
  });

  it("the latest round shows every part, even an empty one", async () => {
    show({ latest: true, empty: true });
    await screen.findByText("Subtasks (0/0)");
    expect(headings()).toEqual(["Subtasks (0/0)", "Questions to other projects", "Attachments", "Activity"]);
  });

  it("each part is a region named by its heading", async () => {
    show({ latest: true });
    expect(await screen.findByRole("region", { name: "Design" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Activity" })).toBeInTheDocument();
  });

  it("an earlier round shows only the parts with something in them", async () => {
    show({ latest: false, empty: true });
    await screen.findByRole("heading", { level: 3, name: "Activity" });
    expect(headings()).toEqual(["Activity"]);
  });

  it("a subtask opens its own page; the agent's plan makes them, so none is added here", async () => {
    show({ latest: true });
    await userEvent.click(await screen.findByRole("button", { name: /Validate the email/ }));
    expect(push).toHaveBeenCalledWith("/projects/PAY/tasks/8");
    expect(screen.queryByLabelText("New subtask")).toBeNull();
  });
});
