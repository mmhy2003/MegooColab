import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TaskDrawer } from "@/components/task/TaskDrawer";

vi.mock("@/components/task/TaskView", () => ({
  TaskView: ({ headerExtra }: { headerExtra: React.ReactNode }) => (
    <div>
      <textarea aria-label="Comment" />
      {headerExtra}
    </div>
  ),
}));

afterEach(cleanup);

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
});
