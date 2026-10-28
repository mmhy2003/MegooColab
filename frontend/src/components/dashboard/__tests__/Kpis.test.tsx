import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Kpis } from "@/components/dashboard/Kpis";

import { numbers } from "./fixture";

afterEach(cleanup);

const tile = (label: string) => screen.getByRole("group", { name: label });

describe("Kpis", () => {
  it("draws Need you and Overdue in pink when above zero", () => {
    render(<Kpis numbers={{ ...numbers, need_you: 3, need_you_over_day: 1, overdue: 0 }} />);
    expect(tile("Need you")).toHaveAttribute("data-alert", "true");
    expect(tile("Overdue")).toHaveAttribute("data-alert", "false");
    expect(screen.getByText("1 over a day old")).toBeInTheDocument();
  });

  it("shows every tile with its small line", () => {
    render(<Kpis numbers={numbers} />);
    expect(tile("Agents working / online")).toHaveTextContent("1/ 2");
    expect(screen.getByText("2 runs queued")).toBeInTheDocument();
    expect(screen.getByText("across 2 projects")).toBeInTheDocument();
    expect(screen.getByText("5 in progress")).toBeInTheDocument();
    expect(screen.getByText("▲ 3 on the 7 days before")).toBeInTheDocument();
    expect(screen.getByText("1 assigned to you")).toBeInTheDocument();
  });

  it("says when done matches or falls behind the 7 days before", () => {
    render(<Kpis numbers={{ ...numbers, done_7d: 4, done_prev_7d: 4 }} />);
    expect(screen.getByText("same as the 7 days before")).toBeInTheDocument();
    cleanup();
    render(<Kpis numbers={{ ...numbers, done_7d: 1, done_prev_7d: 4 }} />);
    expect(screen.getByText("▼ 3 on the 7 days before")).toBeInTheDocument();
  });

  it("shows the success rate, or that no runs finished", () => {
    render(<Kpis numbers={{ ...numbers, success_rate_24h: 0.75 }} />);
    expect(screen.getByText("75% succeeded")).toBeInTheDocument();
    cleanup();
    render(<Kpis numbers={{ ...numbers, success_rate_24h: null }} />);
    expect(screen.getByText("no runs finished")).toBeInTheDocument();
  });
});
