import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { RecentActivity } from "@/components/dashboard/RecentActivity";

import { act } from "./fixture";

afterEach(cleanup);

describe("RecentActivity", () => {
  it("words activity like the task's own list", () => {
    render(
      <RecentActivity
        rows={[
          { ...act, kind: "status_changed", data: { to_column: "c1" }, names: { c1: "In Progress" }, actor_name: "Ana", task_key: "PAY-3" },
          { ...act, id: "e2", kind: "assigned", data: { to_agent: "a1" }, names: { a1: "Docs bot" }, actor_name: null, task_key: "PAY-4" },
        ]}
      />,
    );
    const [first, second] = screen.getAllByRole("listitem");
    expect(first).toHaveTextContent("Ana moved this to In Progress · PAY-3");
    expect(second).toHaveTextContent("MegooColab assigned this to Docs bot · PAY-4");
    expect(screen.getByRole("link", { name: "PAY-3" })).toHaveAttribute("href", "/projects/PAY/board?task=PAY-3");
  });

  it("says when nothing happened yet", () => {
    render(<RecentActivity rows={[]} />);
    expect(screen.getByText("No activity yet.")).toBeInTheDocument();
  });
});
