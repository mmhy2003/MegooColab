import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import Chart from "@/components/a2ui/Chart";

afterEach(cleanup);

// jsdom has no size, so Recharts draws nothing: these tests read the frame and its table view

const twoSeries = {
  kind: "line" as const,
  title: "Failing tests by suite",
  points: [
    { run: "Mon", api: 3, web: 1 },
    { run: "Tue", api: 2, web: 0 },
  ],
  x: "run",
  series: [
    { key: "api", label: "API" },
    { key: "web", label: "Web" },
  ],
};

describe("Chart", () => {
  it("names the chart and shows a legend for two or more series", async () => {
    render(<Chart {...twoSeries} />);
    await screen.findByRole("region", { name: "Failing tests by suite" });
    const legend = screen.getByRole("list", { name: "Legend" });
    expect(within(legend).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["API", "Web"]);
  });

  it("has no legend with one series", async () => {
    render(<Chart {...twoSeries} series={[{ key: "api", label: "API" }]} />);
    await screen.findByRole("region", { name: "Failing tests by suite" });
    expect(within(screen.getByRole("list", { name: "Legend" })).queryAllByRole("listitem")).toEqual([]);
  });

  it("lists every point in the table view, with the unit and gaps", async () => {
    const user = userEvent.setup();
    const points = [
      { day: "Mon", build: 12.5 },
      { day: "Tue", build: null },
      { day: "Wed", build: "3" },
      { day: "Thu", build: 9 },
    ];
    render(<Chart kind="bar" title="Build time" points={points} x="day" series={[{ key: "build", label: "Time" }]} unit="s" />);
    await user.click(await screen.findByRole("button", { name: "Show table" }));
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((th) => th.textContent)).toEqual(["day", "Time (s)"]);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(points.length);
    expect(rows.map((r) => within(r).getAllByRole("cell").map((td) => td.textContent))).toEqual([
      ["Mon", "12.5"],
      ["Tue", "—"],
      ["Wed", "—"],
      ["Thu", "9"],
    ]);
  });

  it("says when there is nothing to draw", async () => {
    const { unmount } = render(<Chart {...twoSeries} points={undefined} />);
    await screen.findByText("No data to draw.");
    unmount();
    render(<Chart {...twoSeries} points={[]} />);
    await screen.findByText("No data to draw.");
  });
});
