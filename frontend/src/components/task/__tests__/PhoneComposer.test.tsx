import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CommentBox } from "@/components/task/CommentBox";
import { PhoneComposer } from "@/components/task/PhoneComposer";

afterEach(cleanup);

function show(onSubmit = vi.fn(async () => {})) {
  render(
    <>
      <button type="button">elsewhere</button>
      <PhoneComposer label="Add a comment…">
        <CommentBox takesImages onSubmit={onSubmit} />
      </PhoneComposer>
    </>,
  );
  const box = screen.getByRole("textbox", { name: "Add a comment" });
  const form = box.closest("[data-phone-form]") as HTMLElement;
  return { box, form, onSubmit };
}

const isOpen = (form: HTMLElement) => !form.classList.contains("max-md:hidden");

describe("PhoneComposer", () => {
  it("starts as a one-line bar and opens on tap", async () => {
    const { box, form } = show();
    expect(isOpen(form)).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Add a comment…" }));
    expect(isOpen(form)).toBe(true);
    expect(box).toHaveFocus();
  });

  it("keeps a draft when closed", async () => {
    const { box, form } = show();
    await userEvent.click(screen.getByRole("button", { name: "Add a comment…" }));
    await userEvent.type(box, "half a thought");
    await userEvent.keyboard("{Escape}");
    expect(isOpen(form)).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Add a comment…" }));
    expect(box).toHaveValue("half a thought");
  });

  it("closes on blur only when empty", async () => {
    const { box, form } = show();
    await userEvent.click(screen.getByRole("button", { name: "Add a comment…" }));
    await userEvent.click(screen.getByRole("button", { name: "elsewhere" }));
    expect(isOpen(form)).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Add a comment…" }));
    await userEvent.type(box, "keep me");
    await userEvent.click(screen.getByRole("button", { name: "elsewhere" }));
    expect(isOpen(form)).toBe(true);
  });

  it("closes after sending", async () => {
    const { box, form, onSubmit } = show();
    await userEvent.click(screen.getByRole("button", { name: "Add a comment…" }));
    await userEvent.type(box, "done");
    fireEvent.submit(box.closest("form")!);
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    await waitFor(() => expect(isOpen(form)).toBe(false));
    expect(box).toHaveValue("");
  });

  it("the image button opens it and the file chooser", async () => {
    const { form } = show();
    const input = form.querySelector('input[type="file"]') as HTMLInputElement;
    const pick = vi.spyOn(input, "click");
    // the bar's image button: the one outside the form
    const bar = screen.getAllByRole("button", { name: "Add images" }).find((b) => !form.contains(b))!;
    await userEvent.click(bar);
    expect(isOpen(form)).toBe(true);
    expect(pick).toHaveBeenCalled();
  });
});
