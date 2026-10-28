import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MyTasks } from "@/components/dashboard/MyTasks";
import type { MyTask } from "@/lib/dashboard";

afterEach(cleanup);

const task = (key: string, due: MyTask["due"], due_date: string): MyTask => ({
  key, title: `Task ${key}`, due, due_date, link: `/projects/PAY/board?task=${key}`,
});

describe("MyTasks", () => {
  it("labels Overdue, Today and This week", () => {
    render(<MyTasks items={[task("PAY-1", "overdue", "2026-10-26"), task("PAY-2", "today", "2026-10-28"), task("PAY-3", "week", "2026-10-30")]} />);
    expect(screen.getByText("Overdue")).toBeInTheDocument();
    expect(screen.getByText("Today")).toBeInTheDocument();
    expect(screen.getByText("This week")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "PAY-1" })).toHaveAttribute("href", "/projects/PAY/board?task=PAY-1");
  });

  it("says when nothing is due", () => {
    render(<MyTasks items={[]} />);
    expect(screen.getByText("No tasks due this week.")).toBeInTheDocument();
  });
});
