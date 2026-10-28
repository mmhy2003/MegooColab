import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DesktopSidebar, SIDEBAR_KEY } from "@/components/shell/DesktopSidebar";
import type { User } from "@/lib/types";

vi.mock("next/navigation", () => ({ usePathname: () => "/projects" }));

const admin = { id: "u1", name: "Ahmed", email: "a@x.io", role: "admin" } as User;

function aside() {
  return screen.getByRole("complementary");
}

beforeEach(() => localStorage.clear());
afterEach(cleanup);

describe("DesktopSidebar", () => {
  it("collapses to a rail and remembers it", () => {
    render(<DesktopSidebar user={admin} />);
    expect(aside()).toHaveAttribute("data-collapsed", "false");
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(aside()).toHaveAttribute("data-collapsed", "true");
    expect(localStorage.getItem(SIDEBAR_KEY)).toBe("collapsed");
    fireEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(aside()).toHaveAttribute("data-collapsed", "false");
    expect(localStorage.getItem(SIDEBAR_KEY)).toBe("expanded");
  });

  it("starts the way it was left", () => {
    localStorage.setItem(SIDEBAR_KEY, "collapsed");
    render(<DesktopSidebar user={admin} />);
    expect(aside()).toHaveAttribute("data-collapsed", "true");
  });

  it("keeps every link named while collapsed, for screen readers and the hover menu", () => {
    localStorage.setItem(SIDEBAR_KEY, "collapsed");
    render(<DesktopSidebar user={admin} />);
    for (const name of ["Projects", "Teams", "Knowledge Base", "Memory", "Questions", "Users", "Audit log"]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
  });

  it("works without browser storage", () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(<DesktopSidebar user={admin} />);
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(aside()).toHaveAttribute("data-collapsed", "true");
    getItem.mockRestore();
    setItem.mockRestore();
  });
});
