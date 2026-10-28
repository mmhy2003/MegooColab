import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FinishedChart } from "@/components/dashboard/FinishedChart";

import { fourteenDays } from "./fixture";

afterEach(cleanup);

describe("FinishedChart", () => {
  it("draws 14 stacked days with first, middle and last labels and totals", () => {
    const days = fourteenDays({ agents: 2, people: 1 });
    days[0] = { ...days[0], people: 1 };
    render(<FinishedChart days={days} />);
    const chart = screen.getByRole("img");
    expect(chart).toHaveAccessibleName("Tasks finished in the last 14 days: 2 by agents, 2 by people");
    expect(chart.querySelectorAll("[data-day]")).toHaveLength(14);
    expect(screen.getByText("by agents · 2")).toBeInTheDocument();
    expect(screen.getByText("by people · 2")).toBeInTheDocument();
    const label = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });
    for (const i of [0, 7, 13]) expect(screen.getByText(label(days[i].day))).toBeInTheDocument();
  });

  it("says when nothing was finished", () => {
    render(<FinishedChart days={fourteenDays({ agents: 0, people: 0 })} />);
    expect(screen.getByText("No tasks finished in the last 14 days.")).toBeInTheDocument();
  });
});
