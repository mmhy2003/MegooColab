import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TaskDrawer } from "@/components/task/TaskDrawer";

vi.mock("@/components/task/TaskView", () => ({
  TaskView: ({ headerExtra }: { headerExtra: React.ReactNode }) => (
    <div>
      <textarea aria-label="Comment" />
      {headerExtra}
    </div>
  ),
}));

const KEY = "tasks.drawerWidth";
const stored = () => JSON.parse(localStorage.getItem(KEY) ?? "null");
const edge = () => screen.getByRole("separator", { name: "Resize task" });
const panel = () => edge().parentElement!;
const shown = () => panel().style.getPropertyValue("--drawer-width");
const open = () => render(<TaskDrawer taskKey="PAY-1" onClose={() => {}} onOpenTask={() => {}} />);

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("innerWidth", 1600); // widest: 1552
  // jsdom has no pointer capture
  Element.prototype.setPointerCapture ??= () => {};
  Element.prototype.releasePointerCapture ??= () => {};
  Element.prototype.hasPointerCapture ??= () => false;
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("TaskDrawer", () => {
  it("stays open on a click outside it, so a half-typed comment is kept", () => {
    const onClose = vi.fn();
    render(<TaskDrawer taskKey="PAY-1" onClose={onClose} onOpenTask={() => {}} />);
    fireEvent.click(document.querySelector("[data-backdrop]")!);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes with its close button and Escape, over a blurred page", () => {
    const onClose = vi.fn();
    render(<TaskDrawer taskKey="PAY-1" onClose={onClose} onOpenTask={() => {}} />);
    expect(document.querySelector("[data-backdrop]")!.className).toMatch(/backdrop-blur/);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("has a resize edge naming its range", () => {
    open();
    expect(edge()).toHaveAttribute("aria-orientation", "vertical");
    expect(edge()).toHaveAttribute("aria-valuemin", "720");
    expect(edge()).toHaveAttribute("aria-valuemax", "1552");
    expect(edge()).toHaveAttribute("aria-valuenow", "896");
    expect(shown()).toBe("896px");
  });

  it("arrow keys, Home and End change the width and keep it", () => {
    open();
    edge().focus();
    fireEvent.keyDown(edge(), { key: "ArrowLeft" });
    expect(edge()).toHaveAttribute("aria-valuenow", "928");
    expect(stored()).toBe(928);
    expect(shown()).toBe("928px");
    fireEvent.keyDown(edge(), { key: "ArrowRight" });
    fireEvent.keyDown(edge(), { key: "ArrowRight" });
    expect(edge()).toHaveAttribute("aria-valuenow", "864");
    expect(stored()).toBe(864);
    fireEvent.keyDown(edge(), { key: "Home" });
    expect(edge()).toHaveAttribute("aria-valuenow", "720");
    expect(stored()).toBe(720);
    fireEvent.keyDown(edge(), { key: "End" });
    expect(edge()).toHaveAttribute("aria-valuenow", "1552");
    expect(stored()).toBe(1552);
  });

  it("Escape on the edge still closes the drawer", () => {
    const onClose = vi.fn();
    render(<TaskDrawer taskKey="PAY-1" onClose={onClose} onOpenTask={() => {}} />);
    fireEvent.keyDown(edge(), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("double-click goes back to 896", () => {
    localStorage.setItem(KEY, "1200");
    open();
    expect(edge()).toHaveAttribute("aria-valuenow", "1200");
    fireEvent.doubleClick(edge());
    expect(stored()).toBe(896);
    expect(edge()).toHaveAttribute("aria-valuenow", "896");
  });

  it("dragging the edge resizes live and keeps the width once, on release", () => {
    open();
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    fireEvent.pointerDown(edge(), { pointerId: 1, button: 0, clientX: 500 });
    fireEvent.pointerMove(edge(), { pointerId: 1, clientX: 400 });
    expect(shown()).toBe("996px");
    expect(stored()).toBeNull();
    expect(edge()).toHaveAttribute("data-dragging");
    fireEvent.pointerMove(edge(), { pointerId: 1, clientX: 300 });
    expect(shown()).toBe("1096px");
    fireEvent.pointerUp(edge(), { pointerId: 1, clientX: 300 });
    expect(stored()).toBe(1096);
    expect(edge()).toHaveAttribute("aria-valuenow", "1096");
    expect(edge()).not.toHaveAttribute("data-dragging");
    expect(setItem.mock.calls.filter(([key]) => key === KEY)).toHaveLength(1);
    setItem.mockRestore();
  });

  it("a drag stops at the limits", () => {
    open();
    fireEvent.pointerDown(edge(), { pointerId: 1, button: 0, clientX: 500 });
    fireEvent.pointerMove(edge(), { pointerId: 1, clientX: 2000 });
    expect(shown()).toBe("720px");
    fireEvent.pointerMove(edge(), { pointerId: 1, clientX: -2000 });
    expect(shown()).toBe("1552px");
  });

  it("a cancelled drag goes back to the kept width", () => {
    open();
    fireEvent.pointerDown(edge(), { pointerId: 1, button: 0, clientX: 500 });
    fireEvent.pointerMove(edge(), { pointerId: 1, clientX: 400 });
    fireEvent.pointerCancel(edge(), { pointerId: 1 });
    expect(shown()).toBe("896px");
    expect(stored()).toBeNull();
  });

  it("a click on the edge stores nothing", () => {
    open();
    fireEvent.pointerDown(edge(), { pointerId: 1, button: 0, clientX: 500 });
    fireEvent.pointerUp(edge(), { pointerId: 1, clientX: 500 });
    expect(stored()).toBeNull();
  });

  it("a stored width wider than the window is squeezed, not lost", () => {
    localStorage.setItem(KEY, "2000");
    open();
    expect(edge()).toHaveAttribute("aria-valuenow", "1552");
    expect(shown()).toBe("2000px");
    expect(stored()).toBe(2000);
  });
});
