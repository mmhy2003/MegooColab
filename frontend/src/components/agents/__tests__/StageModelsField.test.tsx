import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StageModelsField } from "@/components/agents/StageModelsField";
import type { StageModels } from "@/lib/agents";
import type { ModelOption } from "@/lib/types";

const level = (value: string, name: string) => ({ value, name });
const ALL = [level("default", "Default"), level("low", "Low"), level("high", "High"), level("max", "Max")];
const KNOWN: ModelOption[] = [
  { value: "default", name: "Default (recommended)", efforts: ALL },
  { value: "opus", name: "Opus 5.5", efforts: ALL },
  { value: "fable", name: "Fable 5.2", efforts: [level("default", "Default"), level("high", "High"), level("max", "Max")] },
  { value: "claude-haiku-4-5", name: "Haiku 4.5", efforts: [] },
];

function show(value: StageModels = {}) {
  const onSave = vi.fn(async () => {});
  render(<StageModelsField agentModel="opus" agentEffort="high" knownModels={KNOWN} value={value} onSave={onSave} />);
  return onSave;
}

const options = (label: string) => [...screen.getByLabelText(label).querySelectorAll("option")].map((o) => o.textContent);

afterEach(cleanup);

describe("StageModelsField", () => {
  it("lists the five stages, each As above by default", () => {
    show();
    for (const stage of ["Design", "Plan", "Build", "Review", "Finish"]) {
      expect(screen.getByLabelText(`${stage} model`)).toHaveValue("");
      expect(options(`${stage} model`)[0]).toBe("As above (Opus 5.5)");
      expect(options(`${stage} effort`)[0]).toBe("As above (High)");
    }
    expect(screen.getByText("steps and their fixes")).toBeInTheDocument();
  });

  it("a row with its own model offers that model's efforts, and Model default", async () => {
    const onSave = show({ design: { model: "fable" } });
    expect(options("Design effort")).toEqual(["Model default", "High", "Max"]);
    await userEvent.selectOptions(screen.getByLabelText("Plan model"), "fable");
    expect(onSave).toHaveBeenLastCalledWith({ design: { model: "fable" }, plan: { model: "fable" } });
    await userEvent.selectOptions(screen.getByLabelText("Design effort"), "max");
    expect(onSave).toHaveBeenLastCalledWith({ design: { model: "fable", effort: "max" } });
  });

  it("going back to As above drops the row", async () => {
    const onSave = show({ design: { model: "fable" }, plan: { effort: "low" } });
    await userEvent.selectOptions(screen.getByLabelText("Plan effort"), "");
    expect(onSave).toHaveBeenLastCalledWith({ design: { model: "fable" } });
  });

  it("marks rows that differ", () => {
    show({ design: { model: "fable" } });
    expect(screen.getByLabelText("Design model")).toHaveClass("border-violet");
    expect(screen.getByLabelText("Design effort")).toHaveClass("border-violet");
    expect(screen.getByLabelText("Plan model")).not.toHaveClass("border-violet");
  });

  it("picking a model without the row's effort drops the effort, with a note", async () => {
    const onSave = show({ design: { model: "fable", effort: "max" } });
    await userEvent.selectOptions(screen.getByLabelText("Design model"), "claude-haiku-4-5");
    expect(onSave).toHaveBeenLastCalledWith({ design: { model: "claude-haiku-4-5" } });
    expect(screen.getByText("Haiku 4.5 has no Max effort, so Design's effort went back to Model default.")).toBeInTheDocument();
  });

  it("shows a note it is given", () => {
    render(
      <StageModelsField agentModel="opus" agentEffort="high" knownModels={KNOWN} value={{}} onSave={vi.fn()} notice="Plan was reset." />,
    );
    expect(screen.getByText("Plan was reset.")).toBeInTheDocument();
  });
});
