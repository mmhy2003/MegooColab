import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { BoardFilters } from "@/components/board/BoardFilters";

describe("BoardFilters", () => {
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
