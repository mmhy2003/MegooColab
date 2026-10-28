import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { useConfirm, type AskOptions } from "@/components/ui/ConfirmDialog";

afterEach(cleanup);

const DELETE: AskOptions = { tone: "danger", title: "Delete PAY-142?", text: "Its subtasks are deleted too.", ok: "Delete" };

function Asker({ options, text = false }: { options: AskOptions; text?: boolean }) {
  const { ask, askText, dialog } = useConfirm();
  return (
    <>
      <button
        type="button"
        onClick={async () => {
          const answer = text ? await askText({ ...options, field: { label: "Folder name", value: "Runbooks" } }) : await ask(options);
          document.body.dataset.answer = JSON.stringify(answer);
        }}
      >
        go
      </button>
      {dialog}
    </>
  );
}

const answer = () => (document.body.dataset.answer ? JSON.parse(document.body.dataset.answer) : undefined);
// jsdom lays nothing out: the dialog's box is 0x0, so (50, 50) is on the backdrop
const OUTSIDE = { clientX: 50, clientY: 50 };

async function open(options: AskOptions = DELETE, text = false) {
  delete document.body.dataset.answer;
  render(<Asker options={options} text={text} />);
  await userEvent.click(screen.getByRole("button", { name: "go" }));
  return screen.getByRole("alertdialog", { name: options.title });
}

describe("useConfirm", () => {
  it("asks with a title, the consequence and the tone's icon, the safe choice focused", async () => {
    const dialog = await open();
    expect(dialog).toHaveAccessibleDescription("Its subtasks are deleted too.");
    expect(dialog.querySelector("[data-tone=danger]")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(screen.queryByRole("button", { name: "Close" })).toBeNull(); // no ✕: answered with a button
  });

  it("resolves true on the action, false on Cancel", async () => {
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(answer()).toBe(true);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    cleanup();
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(answer()).toBe(false);
  });

  it("Escape and a click outside cancel", async () => {
    await open();
    await userEvent.keyboard("{Escape}");
    expect(answer()).toBe(false);
    cleanup();
    const dialog = await open();
    fireEvent.mouseDown(dialog, OUTSIDE);
    fireEvent.click(dialog, OUTSIDE);
    await waitFor(() => expect(answer()).toBe(false)); // the promise resolves a tick later
  });

  it("uses the action's own words for Cancel when given", async () => {
    await open({ tone: "warn", title: "Discard your changes?", ok: "Discard", cancel: "Keep editing" });
    expect(screen.getByRole("button", { name: "Keep editing" })).toHaveFocus();
  });

  it("asks for text: the field starts selected, empty text cannot be confirmed, Enter confirms", async () => {
    await open({ tone: "info", title: "Rename folder", ok: "Rename" }, true);
    const field = screen.getByRole("textbox", { name: "Folder name" }) as HTMLInputElement;
    expect(field).toHaveFocus();
    expect(field.selectionStart).toBe(0);
    expect(field.selectionEnd).toBe("Runbooks".length);
    await userEvent.clear(field);
    expect(screen.getByRole("button", { name: "Rename" })).toBeDisabled();
    await userEvent.type(field, "  Guides  {Enter}");
    expect(answer()).toBe("Guides");
  });

  it("asking for text and cancelling gives null", async () => {
    await open({ tone: "info", title: "Rename folder", ok: "Rename" }, true);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(answer()).toBeNull();
  });
});
