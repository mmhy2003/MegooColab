import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Dialog } from "@/components/ui/Dialog";

afterEach(cleanup);

// jsdom lays nothing out: the dialog's box is 0x0 at the origin, so (50, 50) is outside it, on the backdrop.
const OUTSIDE = { clientX: 50, clientY: 50 };

function open(props: { dismissible?: boolean } = {}) {
  const onClose = vi.fn();
  render(
    <Dialog open title="New team" onClose={onClose} {...props}>
      <input aria-label="Name" data-autofocus />
    </Dialog>,
  );
  return { onClose, dialog: screen.getByRole("dialog", { name: "New team" }) };
}

describe("Dialog", () => {
  it("stays open on a click outside it, so nothing typed is lost", () => {
    const { onClose, dialog } = open();
    fireEvent.mouseDown(dialog, OUTSIDE);
    fireEvent.click(dialog, OUTSIDE);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes on a click outside it when dismissible", () => {
    const { onClose, dialog } = open({ dismissible: true });
    fireEvent.mouseDown(dialog, OUTSIDE);
    fireEvent.click(dialog, OUTSIDE);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("does not close when a press starts inside and ends outside, as when selecting text", () => {
    const { onClose, dialog } = open({ dismissible: true });
    fireEvent.mouseDown(screen.getByLabelText("Name"));
    fireEvent.click(dialog, OUTSIDE);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does not close on a click inside it", () => {
    const { onClose } = open({ dismissible: true });
    fireEvent.mouseDown(screen.getByLabelText("Name"));
    fireEvent.click(screen.getByLabelText("Name"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("opens as a modal, so the browser draws a backdrop and Escape works", () => {
    const showModal = vi.fn(function (this: HTMLDialogElement) {
      this.setAttribute("open", "");
    });
    HTMLDialogElement.prototype.showModal = showModal;
    try {
      open();
      expect(showModal).toHaveBeenCalledOnce();
    } finally {
      delete (HTMLDialogElement.prototype as Partial<HTMLDialogElement>).showModal;
    }
  });

  it("focuses the field marked data-autofocus, though the browser focuses the first button on open", () => {
    // what a browser's showModal() does: open, and focus the first focusable element (here the close button)
    HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
      this.setAttribute("open", "");
      this.querySelector<HTMLElement>("button, input")?.focus();
    };
    try {
      open();
      expect(document.activeElement).toBe(screen.getByLabelText("Name"));
    } finally {
      delete (HTMLDialogElement.prototype as Partial<HTMLDialogElement>).showModal;
    }
  });

  it("blurs the page behind it", () => {
    const { dialog } = open();
    expect(dialog.className).toMatch(/backdrop:backdrop-blur/);
  });
});
