import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TaskPageCard } from "@/components/task/TaskPageCard";

vi.mock("@/components/task/TaskView", () => ({
  TaskView: ({ headerExtra, expanded }: { headerExtra: React.ReactNode; expanded?: boolean }) => (
    <div data-expanded={String(!!expanded)}>
      <textarea aria-label="Comment" />
      {headerExtra}
    </div>
  ),
}));

const card = () => document.querySelector("[data-task-page]") as HTMLElement;
const show = () => render(<TaskPageCard taskKey="PAY-1" onOpenTask={() => {}} onDeleted={() => {}} />);

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("TaskPageCard expanded", () => {
  it("a desktop button expands the task over the whole window, and collapses it again", async () => {
    show();
    const expand = screen.getByRole("button", { name: "Expand task" });
    expect(expand.closest(".max-md\\:hidden")).not.toBeNull(); // desktop only
    expect(card()).not.toHaveClass("md:fixed");
    await userEvent.click(expand);
    // fixed over the menu and the top bar; the height the page gave it to fill the window gives way
    expect(card()).toHaveClass("md:fixed", "md:inset-0", "md:z-40", "md:h-auto!");
    expect(document.querySelector("[data-expanded]")).toHaveAttribute("data-expanded", "true");
    await userEvent.click(screen.getByRole("button", { name: "Collapse task" }));
    expect(card()).not.toHaveClass("md:fixed");
    expect(document.querySelector("[data-expanded]")).toHaveAttribute("data-expanded", "false");
  });

  it("is remembered in this browser, apart from chats", async () => {
    show();
    await userEvent.click(screen.getByRole("button", { name: "Expand task" }));
    expect(window.localStorage.getItem("tasks.expanded")).toBe("true");
    expect(window.localStorage.getItem("chats.expanded")).toBeNull();
    cleanup();
    show();
    expect(card()).toHaveClass("md:fixed");
  });

  it("Esc collapses it", async () => {
    show();
    await userEvent.click(screen.getByRole("button", { name: "Expand task" }));
    await userEvent.keyboard("{Escape}");
    expect(card()).not.toHaveClass("md:fixed");
  });

  it("Esc while typing leaves it expanded", async () => {
    show();
    await userEvent.click(screen.getByRole("button", { name: "Expand task" }));
    await userEvent.click(screen.getByRole("textbox", { name: "Comment" }));
    await userEvent.keyboard("half a thought{Escape}");
    expect(card()).toHaveClass("md:fixed");
  });

  it("Esc with something open on top leaves it expanded", async () => {
    show();
    await userEvent.click(screen.getByRole("button", { name: "Expand task" }));
    const menu = document.createElement("div");
    menu.setAttribute("role", "menu");
    document.body.append(menu);
    await userEvent.keyboard("{Escape}");
    menu.remove();
    expect(card()).toHaveClass("md:fixed");
  });

  it("Esc does nothing on a narrow screen, where expanding doesn't show", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: !q.includes("min-width"), media: q, addEventListener() {}, removeEventListener() {} }));
    show();
    await userEvent.click(screen.getByRole("button", { name: "Expand task" }));
    await userEvent.keyboard("{Escape}");
    expect(card()).toHaveClass("md:fixed");
  });
});
