import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ModelField } from "@/components/agents/ModelField";
import type { ModelOption } from "@/lib/types";

const level = (value: string, name: string) => ({ value, name });
const ALL = [level("default", "Default"), level("low", "Low"), level("medium", "Medium"), level("high", "High"), level("xhigh", "Xhigh"), level("max", "Max")];
const KNOWN: ModelOption[] = [
  { value: "default", name: "Default (recommended)", efforts: ALL },
  { value: "opus", name: "Opus 5.5", efforts: ALL },
  { value: "claude-opus-4-6", name: "Opus 4.6", efforts: ALL.filter((l) => l.value !== "xhigh") },
  { value: "claude-haiku-4-5", name: "Haiku 4.5", efforts: [] },
];

function renderField(model: string | null, effort: string | null = null, known = KNOWN) {
  const onSave = vi.fn(async () => {});
  render(<ModelField model={model} effort={effort} knownModels={known} onSave={onSave} />);
  return onSave;
}

const options = (label: string) => [...screen.getByLabelText(label).querySelectorAll("option")].map((o) => o.textContent);

afterEach(cleanup);

describe("ModelField model", () => {
  it("lists the models the agent offered, with the program's default first", () => {
    renderField(null);
    expect(options("Model")).toEqual(["Program default", "Opus 5.5", "Opus 4.6", "Haiku 4.5", "Other…"]);
    expect(screen.getByLabelText("Model")).toHaveValue("");
    expect(screen.getByText("Runs use the program's own default model.")).toBeInTheDocument();
  });

  it("saves the model picked, and goes back to the default", async () => {
    const onSave = renderField("opus");
    expect(screen.getByLabelText("Model")).toHaveValue("opus");
    expect(screen.getByText("Runs start on Opus 5.5.")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Model"), "claude-opus-4-6");
    expect(onSave).toHaveBeenLastCalledWith({ model: "claude-opus-4-6" });
    await userEvent.selectOptions(screen.getByLabelText("Model"), "");
    expect(onSave).toHaveBeenLastCalledWith({ model: null });
  });

  it("keeps a model typed earlier that the agent didn't list", () => {
    renderField("opus[1m]");
    expect(screen.getByLabelText("Model")).toHaveValue("opus[1m]");
    expect(screen.getByRole("option", { name: "opus[1m]" })).toBeInTheDocument();
  });

  it("shows a model saved by its name, such as a default model, as that listed model", () => {
    renderField("Opus 5.5");
    expect(screen.getByLabelText("Model")).toHaveValue("opus");
    expect(options("Model")).toHaveLength(5);
    expect(screen.getByText("Runs start on Opus 5.5.")).toBeInTheDocument();
  });

  it("lets a name be typed with Other…", async () => {
    const onSave = renderField(null);
    await userEvent.selectOptions(screen.getByLabelText("Model"), "Other…");
    await userEvent.type(screen.getByLabelText("Model"), "  sonnet ");
    await userEvent.click(screen.getByRole("button", { name: "Save model" }));
    expect(onSave).toHaveBeenLastCalledWith({ model: "sonnet" });
  });

  it("before its first run, asks for a name and says the lists come later", async () => {
    const onSave = renderField(null, null, []);
    expect(screen.getByLabelText("Model")).toHaveValue("");
    expect(screen.getByText(/each one's effort levels, are listed here after its first run/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save model" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Model"), "opus");
    await userEvent.click(screen.getByRole("button", { name: "Save model" }));
    expect(onSave).toHaveBeenLastCalledWith({ model: "opus" });
  });

  it("clearing a typed name goes back to the default", async () => {
    const onSave = renderField("opus", null, []);
    await userEvent.clear(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("button", { name: "Save model" }));
    expect(onSave).toHaveBeenLastCalledWith({ model: null });
  });
});

describe("ModelField effort", () => {
  it("offers the levels of the chosen model, after Model default", () => {
    renderField("opus", "high");
    expect(options("Effort")).toEqual(["Model default", "Low", "Medium", "High", "Xhigh", "Max"]);
    expect(screen.getByLabelText("Effort")).toHaveValue("high");
    expect(screen.getByText("Runs start on Opus 5.5 with High effort.")).toBeInTheDocument();
  });

  it("saves the level picked, and goes back to the model's default", async () => {
    const onSave = renderField("opus");
    await userEvent.selectOptions(screen.getByLabelText("Effort"), "max");
    expect(onSave).toHaveBeenLastCalledWith({ effort: "max" });
    await userEvent.selectOptions(screen.getByLabelText("Effort"), "");
    expect(onSave).toHaveBeenLastCalledWith({ effort: null });
  });

  it("goes back to Model default when the model picked lacks the level, and says so", async () => {
    const onSave = renderField("opus", "xhigh");
    await userEvent.selectOptions(screen.getByLabelText("Model"), "claude-opus-4-6");
    expect(onSave).toHaveBeenLastCalledWith({ model: "claude-opus-4-6", effort: null });
    expect(screen.getByRole("status")).toHaveTextContent("Opus 4.6 has no Xhigh effort, so Effort went back to Model default.");
  });

  it("keeps the level when the model picked has it", async () => {
    const onSave = renderField("opus", "high");
    await userEvent.selectOptions(screen.getByLabelText("Model"), "claude-opus-4-6");
    expect(onSave).toHaveBeenLastCalledWith({ model: "claude-opus-4-6" });
  });

  it("says a model without effort is not adjustable", () => {
    renderField("claude-haiku-4-5");
    expect(screen.getByLabelText("Effort")).toBeDisabled();
    expect(options("Effort")).toEqual(["Not adjustable"]);
  });

  it("offers the usual levels for a model whose own aren't known yet", () => {
    renderField("Opus 5.5", "High", []);
    expect(options("Effort")).toEqual(["Model default", "Low", "Medium", "High", "Xhigh", "Max"]);
    expect(screen.getByLabelText("Effort")).toHaveValue("high");
    expect(screen.getByText("Runs start on Opus 5.5 with High effort.")).toBeInTheDocument();
  });
});
