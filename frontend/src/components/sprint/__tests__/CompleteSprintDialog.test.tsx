import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CompleteSprintDialog } from "@/components/sprint/CompleteSprintDialog";
import type { Sprint } from "@/lib/types";

const sprint = (id: string, name: string, state: Sprint["state"], start: string): Sprint => ({
  id,
  project_id: "p1",
  name,
  goal: "",
  start_date: start,
  end_date: start,
  state,
  completed_at: null,
  committed_points: null,
  completed_points: null,
});

const ACTIVE = sprint("s1", "Sprint 1", "active", "2026-11-02");
const LATER = sprint("s3", "Sprint 3", "planned", "2026-11-23");
const NEXT = sprint("s2", "Sprint 2", "planned", "2026-11-09");

describe("CompleteSprintDialog", () => {
  it("offers the backlog and planned sprints, next one first and preselected", () => {
    render(<CompleteSprintDialog sprint={ACTIVE} openCount={3} planned={[LATER, NEXT]} onConfirm={vi.fn()} onClose={vi.fn()} />);
    const select = screen.getByLabelText(/move 3 open tasks to/i) as HTMLSelectElement;
    expect([...select.options].map((o) => o.textContent)).toEqual(["Sprint 2", "Sprint 3", "Backlog"]);
    expect(select.value).toBe("s2");
  });

  it("sends the chosen destination", () => {
    const onConfirm = vi.fn();
    render(<CompleteSprintDialog sprint={ACTIVE} openCount={3} planned={[NEXT]} onConfirm={onConfirm} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/move 3 open tasks to/i), { target: { value: "backlog" } });
    fireEvent.click(screen.getByRole("button", { name: /complete sprint/i }));
    expect(onConfirm).toHaveBeenCalledWith("backlog");
  });

  it("defaults to the backlog when nothing is planned", () => {
    const onConfirm = vi.fn();
    render(<CompleteSprintDialog sprint={ACTIVE} openCount={0} planned={[]} onConfirm={onConfirm} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /complete sprint/i }));
    expect(onConfirm).toHaveBeenCalledWith("backlog");
  });
});
