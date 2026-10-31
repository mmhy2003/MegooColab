import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ModelField } from "@/components/agents/ModelField";

const KNOWN = [
  { value: "default", name: "Default (recommended)" },
  { value: "opus", name: "Opus 4.7" },
  { value: "sonnet", name: "Sonnet 4.6" },
];

function renderField(model: string | null, known = KNOWN, onSave = vi.fn(async () => {})) {
  render(<ModelField model={model} knownModels={known} onSave={onSave} />);
  return onSave;
}

afterEach(cleanup);

describe("ModelField", () => {
  it("lists the models the agent offered, with the program's default first", () => {
    renderField(null);
    const select = screen.getByLabelText("Model");
    expect([...select.querySelectorAll("option")].map((o) => o.textContent)).toEqual([
      "Program default",
      "Opus 4.7",
      "Sonnet 4.6",
      "Other…",
    ]);
    expect(select).toHaveValue("");
    expect(screen.getByText("Runs use the program's own default model.")).toBeInTheDocument();
  });

  it("saves the model picked, and goes back to the default", async () => {
    const onSave = renderField("opus");
    expect(screen.getByLabelText("Model")).toHaveValue("opus");
    expect(screen.getByText("Runs start on Opus 4.7.")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Model"), "sonnet");
    expect(onSave).toHaveBeenLastCalledWith("sonnet");
    await userEvent.selectOptions(screen.getByLabelText("Model"), "");
    expect(onSave).toHaveBeenLastCalledWith(null);
  });

  it("keeps a model typed earlier that the agent didn't list", () => {
    renderField("opus[1m]");
    expect(screen.getByLabelText("Model")).toHaveValue("opus[1m]");
    expect(screen.getByRole("option", { name: "opus[1m]" })).toBeInTheDocument();
  });

  it("shows a model saved by its name, such as a default model, as that listed model", () => {
    renderField("opus 4.7");
    expect(screen.getByLabelText("Model")).toHaveValue("opus");
    expect(screen.getAllByRole("option")).toHaveLength(4);
    expect(screen.getByText("Runs start on Opus 4.7.")).toBeInTheDocument();
  });

  it("lets a name be typed with Other…", async () => {
    const onSave = renderField(null);
    await userEvent.selectOptions(screen.getByLabelText("Model"), "Other…");
    await userEvent.type(screen.getByLabelText("Model"), "  haiku ");
    await userEvent.click(screen.getByRole("button", { name: "Save model" }));
    expect(onSave).toHaveBeenLastCalledWith("haiku");
  });

  it("before its first run, asks for a name and says the list comes later", async () => {
    const onSave = renderField(null, []);
    expect(screen.getByLabelText("Model")).toHaveValue("");
    expect(screen.getByText(/the models it offers are listed here after its first run/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save model" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Model"), "opus");
    await userEvent.click(screen.getByRole("button", { name: "Save model" }));
    expect(onSave).toHaveBeenLastCalledWith("opus");
  });

  it("clearing a typed name goes back to the default", async () => {
    const onSave = renderField("opus", []);
    await userEvent.clear(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("button", { name: "Save model" }));
    expect(onSave).toHaveBeenLastCalledWith(null);
  });
});
