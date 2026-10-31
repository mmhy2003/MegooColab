import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const back = vi.fn();
const push = vi.fn();
vi.mock("next/navigation", () => ({ usePathname: () => "/projects/PAY/taskz", useRouter: () => ({ back, push }) }));

import { NotFoundView } from "@/components/shell/NotFound";

afterEach(() => {
  cleanup();
  back.mockClear();
  push.mockClear();
});

describe("NotFoundView", () => {
  it("says the page doesn't exist and shows the address that was tried", () => {
    render(<NotFoundView />);
    expect(screen.getByRole("heading", { level: 1, name: "This page doesn't exist" })).toBeInTheDocument();
    expect(screen.getByText("/projects/PAY/taskz")).toBeInTheDocument();
  });

  it("links to the Dashboard", () => {
    render(<NotFoundView />);
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
  });

  it("goes back to the page the person came from", () => {
    window.history.pushState({}, "", "/somewhere");
    render(<NotFoundView />);
    fireEvent.click(screen.getByRole("button", { name: "Go back" }));
    expect(back).toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it("opens the Dashboard when there is no earlier page to go back to", () => {
    vi.spyOn(window.history, "length", "get").mockReturnValue(1);
    render(<NotFoundView />);
    fireEvent.click(screen.getByRole("button", { name: "Go back" }));
    expect(push).toHaveBeenCalledWith("/");
    expect(back).not.toHaveBeenCalled();
    vi.restoreAllMocks();
  });

  it("opens the Dashboard rather than going back to another site or a new tab's start page", () => {
    window.history.pushState({}, "", "/somewhere"); // the browser's history has an entry, just not one of ours
    vi.stubGlobal("navigation", { canGoBack: false });
    render(<NotFoundView />);
    fireEvent.click(screen.getByRole("button", { name: "Go back" }));
    expect(push).toHaveBeenCalledWith("/");
    expect(back).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("goes back when the browser says the earlier page is one of ours", () => {
    vi.spyOn(window.history, "length", "get").mockReturnValue(1);
    vi.stubGlobal("navigation", { canGoBack: true });
    render(<NotFoundView />);
    fireEvent.click(screen.getByRole("button", { name: "Go back" }));
    expect(back).toHaveBeenCalled();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });
});
