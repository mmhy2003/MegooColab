import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BoardFilters } from "@/components/board/BoardFilters";

afterEach(cleanup);

describe("BoardFilters", () => {
  it("a long epic or person can't widen a phone's page", () => {
    const epics = [{ key: "MOB-3", title: "Rework the checkout flow for every payment provider we support today" }];
    render(<BoardFilters value={{}} onChange={vi.fn()} users={[]} labels={[]} epics={epics as never} />);
    for (const name of ["Filter by assignee", "Filter by label", "Filter by epic"]) {
      expect(screen.getByRole("combobox", { name })).toHaveClass("min-w-0", "max-w-full");
    }
  });

  it("needs-you toggle sets the query", async () => {
    const onChange = vi.fn();
    const { rerender } = render(<BoardFilters value={{ q: "x" }} onChange={onChange} users={[]} labels={[]} epics={[]} />);
    await userEvent.click(screen.getByLabelText("Needs you"));
    expect(onChange).toHaveBeenCalledWith({ q: "x", needs_you: "true" });
    rerender(<BoardFilters value={{ needs_you: "true" }} onChange={onChange} users={[]} labels={[]} epics={[]} />);
    await userEvent.click(screen.getByLabelText("Needs you"));
    expect(onChange).toHaveBeenLastCalledWith({ needs_you: undefined });
  });
});
