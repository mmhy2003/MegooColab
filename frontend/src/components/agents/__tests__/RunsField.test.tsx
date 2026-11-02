import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RunsField, parseRuns, runsLabel } from "@/components/agents/RunsField";

afterEach(cleanup);

function renderField(max: number, running = 0) {
  const onSave = vi.fn(async () => {});
  render(<RunsField max={max} running={running} onSave={onSave} />);
  return onSave;
}

describe("parseRuns", () => {
  it("takes a whole number from 1 to 3", () => {
    expect(["1", "2", " 3 "].map(parseRuns)).toEqual([1, 2, 3]);
    expect(["0", "4", "", "1.5", "-1", "two"].map(parseRuns)).toEqual([null, null, null, null, null, null]);
  });
});

describe("runsLabel", () => {
  it("counts the running runs against the limit, and says when lowering left more running", () => {
    expect(runsLabel(0, 3)).toBeNull();
    expect(runsLabel(1, 3)).toBe("1 of 3 running");
    expect(runsLabel(3, 1)).toBe("3 running, limit 1");
  });
});

describe("RunsField", () => {
  it("raises the limit with + or by typing, and saves it", async () => {
    const onSave = renderField(1);
    const input = screen.getByLabelText("Runs at once");
    expect(input).toHaveValue(1);
    expect(screen.getByRole("button", { name: "Save runs at once" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Fewer runs at once" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "More runs at once" }));
    expect(input).toHaveValue(2);
    await userEvent.clear(input);
    await userEvent.type(input, "3");
    expect(screen.getByRole("button", { name: "More runs at once" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Save runs at once" }));
    expect(onSave).toHaveBeenLastCalledWith(3);
  });

  it("lowers the limit", async () => {
    const onSave = renderField(3);
    await userEvent.click(screen.getByRole("button", { name: "Fewer runs at once" }));
    await userEvent.click(screen.getByRole("button", { name: "Save runs at once" }));
    expect(onSave).toHaveBeenLastCalledWith(2);
  });

  it("refuses a number outside 1 to 3", async () => {
    const onSave = renderField(2);
    const input = screen.getByLabelText("Runs at once");
    await userEvent.clear(input);
    await userEvent.type(input, "5");
    expect(screen.getByText("Choose a whole number from 1 to 3.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save runs at once" })).toBeDisabled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("says what happens to runs already going after lowering it", () => {
    renderField(1, 3);
    expect(
      screen.getByText("3 runs are going now. They finish as they are; nothing new starts until they have finished."),
    ).toBeInTheDocument();
    cleanup();
    renderField(2, 3);
    expect(
      screen.getByText("3 runs are going now. They finish as they are; nothing new starts until fewer than 2 are running."),
    ).toBeInTheDocument();
    cleanup();
    renderField(3, 1);
    expect(screen.getByText("Up to 3 tasks and chats at the same time.")).toBeInTheDocument();
  });
});
