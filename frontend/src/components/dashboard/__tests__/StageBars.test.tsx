import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { StageBars } from "@/components/dashboard/StageBars";

import { stageRow } from "./fixture";

afterEach(cleanup);

const zeros = ["brainstorm", "design", "review", "done"].map((s) => stageRow(s as "brainstorm"));
const segments = (group: HTMLElement) =>
  Array.from(group.querySelectorAll<HTMLElement>("[data-segment]")).map((el) => el.style.width);

describe("StageBars", () => {
  it("splits each stage bar into working, waiting and paused, scaled to the largest", () => {
    render(<StageBars stages={{ rows: [stageRow("build", 2, 1, 1), stageRow("plan", 0, 2, 0), ...zeros], done_30d: 31 }} />);
    expect(segments(screen.getByRole("group", { name: "Build" }))).toEqual(["50%", "25%", "25%"]);
    expect(segments(screen.getByRole("group", { name: "Plan" }))).toEqual(["0%", "50%", "0%"]);
    expect(within(screen.getByRole("group", { name: "Done" })).getByText("31")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Finishing" })).toBeInTheDocument();
    expect(screen.getByText("paused or manual")).toBeInTheDocument();
  });

  it("says when no workflow is in progress", () => {
    render(<StageBars stages={{ rows: [stageRow("build"), stageRow("plan"), ...zeros], done_30d: 0 }} />);
    expect(screen.getByText("No workflows in progress.")).toBeInTheDocument();
  });
});
