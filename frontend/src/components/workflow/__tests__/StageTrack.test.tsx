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

  it("shows the waiting state in text and with a pink outline", () => {
    const { container } = render(<StageTrack stage="plan" status="waiting_human" compact />);
    expect(screen.getByText(/waiting for you/)).toBeInTheDocument();
    expect(container.querySelector('[data-state="current"]')).toHaveClass("border-pink");
  });

  it("fills every segment once finished", () => {
    const { container } = render(<StageTrack stage="done" status="finished" />);
    expect(container.querySelectorAll('[data-state="done"]')).toHaveLength(6);
  });
});
