import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { ChartFrame } from "@/components/ui/ChartFrame";

afterEach(cleanup);

function show() {
  render(
    <ChartFrame
      title="Velocity"
      legend={[{ label: "A", color: "#000" }, { label: "B", color: "#111" }]}
      table={{ headers: ["x", "A", "B"], rows: [["one", 1, 2]] }}
    >
      <p>drawn</p>
    </ChartFrame>,
  );
}

describe("ChartFrame", () => {
  it("names the chart and lists its legend", () => {
    show();
    screen.getByRole("region", { name: "Velocity" });
    const legend = screen.getByRole("list", { name: "Legend" });
    expect(within(legend).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["A", "B"]);
    expect(screen.getByText("drawn")).toBeTruthy();
  });

  it("switches to a table and back", async () => {
    const user = userEvent.setup();
    show();
    await user.click(screen.getByRole("button", { name: "Show table" }));
    expect(screen.queryByText("drawn")).toBeNull();
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((th) => th.textContent)).toEqual(["x", "A", "B"]);
    const rows = within(table).getAllByRole("row");
    expect(within(rows[1]).getAllByRole("cell").map((td) => td.textContent)).toEqual(["one", "1", "2"]);
    const back = screen.getByRole("button", { name: "Show chart" });
    expect(back.getAttribute("aria-pressed")).toBe("true");
    await user.click(back);
    expect(screen.getByText("drawn")).toBeTruthy();
  });
});
