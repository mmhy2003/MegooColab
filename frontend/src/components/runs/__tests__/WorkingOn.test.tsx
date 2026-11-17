import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { run } from "@/components/dashboard/__tests__/fixture";
import { WorkingOn } from "@/components/runs/WorkingOn";

afterEach(cleanup);

const runs = [
  run(),
  run({ run_id: "r2", kind: "chat", title: "Pricing ideas", task_key: null, chat_id: "c1", link: "/chats/c1", stage: null }),
  run({ run_id: "r3", kind: "question", title: null, task_key: null, question_key: "PAY-Q12", link: "/questions/q1", stage: null }),
];

const list = () => screen.getByRole("list", { name: "Working on" });

describe("WorkingOn", () => {
  it("lists every run when not collapsed", () => {
    render(<WorkingOn runs={runs} />);
    expect(within(list()).getAllByRole("listitem")).toHaveLength(3);
    expect(within(list()).getAllByRole("link")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: "+2 more" })).toBeNull();
  });

  it("with titles shows a task's title after its key", () => {
    const { unmount } = render(<WorkingOn runs={runs} titles />);
    expect(screen.getByText("Fix the login")).toBeInTheDocument();
    unmount();
    render(<WorkingOn runs={runs} />);
    expect(screen.queryByText("Fix the login")).toBeNull();
    expect(screen.getByRole("link", { name: "PAY-14" })).toHaveAttribute("title", "Fix the login");
  });

  it("collapsed shows the newest and opens the rest in place", async () => {
    const user = userEvent.setup();
    render(<WorkingOn runs={runs} collapsed />);
    expect(within(list()).getAllByRole("listitem")).toHaveLength(1);
    const more = screen.getByRole("button", { name: "+2 more" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    await user.click(more);
    expect(within(list()).getAllByRole("listitem")).toHaveLength(3);
    const less = screen.getByRole("button", { name: "Show less" });
    expect(less).toHaveAttribute("aria-expanded", "true");
    await user.click(less);
    expect(within(list()).getAllByRole("listitem")).toHaveLength(1);
  });

  it("one run has no button; none shows a dash", () => {
    const { unmount } = render(<WorkingOn runs={[run()]} collapsed />);
    expect(screen.queryByRole("button")).toBeNull();
    unmount();
    render(<WorkingOn runs={[]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("each entry shows its status", () => {
    render(<WorkingOn runs={runs} />);
    expect(screen.getByText("Build · Step 2 of 3")).toBeInTheDocument();
  });
});
