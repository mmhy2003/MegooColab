import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Select } from "@/components/ui/Select";

afterEach(cleanup);

describe("Select", () => {
  it("Select stays inside a narrow parent", () => {
    // a native select is as wide as its longest option unless it may shrink
    render(
      <Select label="Project">
        <option>{"A project with a very long name ".repeat(6)}</option>
      </Select>,
    );
    const select = screen.getByLabelText("Project");
    expect(select).toHaveClass("min-w-0");
    expect(select.parentElement).toHaveClass("min-w-0");
  });
});
