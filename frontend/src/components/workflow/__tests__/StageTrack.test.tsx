import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StageTrack } from "@/components/workflow/StageTrack";

describe("StageTrack", () => {
  it("marks current and completed stages with accessible label", () => {
    const { container } = render(<StageTrack stage="build" status="running" />);
    expect(screen.getByLabelText("Stage: Build (4 of 6)")).toBeInTheDocument();
    const states = [...container.querySelectorAll("[data-stage]")].map((e) => e.getAttribute("data-state"));
    expect(states).toEqual(["done", "done", "done", "current", "todo", "todo"]);
  });

  it("shows the waiting state in text and with a pink outline and pink glow", () => {
    const { container } = render(<StageTrack stage="plan" status="waiting_human" canAct compact />);
    expect(screen.getByText(/waiting for you/)).toBeInTheDocument();
    const cur = container.querySelector('[data-state="current"]');
    expect(cur).toHaveClass("border-pink", "glow-box-pink");
    expect(cur).not.toHaveClass("glow-box");
  });

  it("uses neutral wording for viewers who cannot act", () => {
    const { rerender } = render(<StageTrack stage="plan" status="waiting_human" compact />);
    expect(screen.getByText(/waiting on a person/)).toBeInTheDocument();
    expect(screen.queryByText(/for you/i)).not.toBeInTheDocument();
    rerender(<StageTrack stage="plan" status="waiting_human" />);
    expect(screen.getByText("Waiting on a person")).toBeInTheDocument();
    rerender(<StageTrack stage="plan" status="waiting_human" canAct />);
    expect(screen.getByText("Waiting for you")).toBeInTheDocument();
  });

  it("states running, paused and idle in text, not only by animation", () => {
    const { rerender } = render(<StageTrack stage="build" status="paused" compact />);
    expect(screen.getByText(/paused/)).toBeInTheDocument();
    rerender(<StageTrack stage="build" status="running" compact />);
    expect(screen.getByText(/running/)).toBeInTheDocument();
    rerender(<StageTrack stage="build" status="idle" compact />);
    expect(screen.getByText(/not started/)).toBeInTheDocument();
    rerender(<StageTrack stage="build" status="running" />);
    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it("draws done segments differently from the current one", () => {
    const { container } = render(<StageTrack stage="build" status="running" />);
    const done = container.querySelector('[data-state="done"]')!;
    const cur = container.querySelector('[data-state="current"]')!;
    expect(done.className).not.toBe(cur.className);
    expect(done).toHaveClass("bg-cyan-ink/50");
    expect(done).not.toHaveClass("glow-box");
  });

  it("fills every segment once finished", () => {
    const { container } = render(<StageTrack stage="done" status="finished" />);
    expect(container.querySelectorAll('[data-state="done"]')).toHaveLength(6);
  });
});
