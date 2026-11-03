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

  it("all 8 tiles stay, each with its second line, in a sideways row on phones", () => {
    const { container } = render(<Kpis numbers={{ ...numbers, need_you_over_day: 2 }} />);
    const row = container.querySelector("[data-scroll-x]")!;
    expect(row).toHaveAttribute("data-scroll-x");
    const tiles = Array.from(row.querySelectorAll("[data-tile]"));
    expect(tiles).toHaveLength(8);
    for (const t of tiles) expect(t).toHaveClass("max-md:w-36", "shrink-0");
    expect(screen.getByText("2 over a day old")).toBeInTheDocument();
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

  it("counts open chats and the ones waiting on you", () => {
    render(<Kpis numbers={{ ...numbers, open_chats: 5, chats_waiting_on_you: 2 }} />);
    expect(tile("Open chats")).toHaveTextContent("5");
    expect(screen.getByText("2 waiting on you")).toBeInTheDocument();
    expect(tile("Open chats")).toHaveAttribute("data-alert", "true");
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
