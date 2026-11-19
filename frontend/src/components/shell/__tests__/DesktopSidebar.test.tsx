import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DesktopSidebar, SIDEBAR_KEY } from "@/components/shell/DesktopSidebar";
import { LABEL_HIDDEN } from "@/components/shell/Sidebar";
import type { User } from "@/lib/types";

vi.mock("next/navigation", () => ({ usePathname: () => "/projects" }));

const admin = { id: "u1", name: "Ahmed", email: "a@x.io", role: "admin" } as User;

function aside() {
  return screen.getByRole("complementary");
}

// the Dashboard entry asks for its badge count; the footer asks for the running version
function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (url: RequestInfo | URL) =>
        new Response(
          JSON.stringify(
            String(url).includes("/api/updates")
              ? { app_version: "0.23.1", app: null, runner: null }
              : { needs_you: 0 },
          ),
          { status: 200 },
        ),
    ),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("DesktopSidebar", () => {
  it("collapses to a rail and remembers it", () => {
    wrap(<DesktopSidebar user={admin} />);
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
    wrap(<DesktopSidebar user={admin} />);
    expect(aside()).toHaveAttribute("data-collapsed", "true");
  });

  it("keeps every link named while collapsed, for screen readers and the hover menu", () => {
    localStorage.setItem(SIDEBAR_KEY, "collapsed");
    wrap(<DesktopSidebar user={admin} />);
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
    wrap(<DesktopSidebar user={admin} />);
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(aside()).toHaveAttribute("data-collapsed", "true");
    getItem.mockRestore();
    setItem.mockRestore();
  });

  it("shows the version at the foot, after the Collapse button", async () => {
    wrap(<DesktopSidebar user={admin} />);
    const v = await screen.findByRole("link", { name: /MegooColab 0\.23\.1/ });
    expect(aside()).toContainElement(v);
    expect(v).toHaveTextContent("v0.23.1");
    const collapse = screen.getByRole("button", { name: "Collapse sidebar" });
    expect(collapse.compareDocumentPosition(v) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(v.className).toContain("ml-auto");
    expect(v.className).not.toContain("opacity-0");
  });

  it("hides the version on the closed rail, like the labels", async () => {
    localStorage.setItem(SIDEBAR_KEY, "collapsed");
    wrap(<DesktopSidebar user={admin} />);
    const v = await screen.findByRole("link", { name: /MegooColab 0\.23\.1/ });
    expect(LABEL_HIDDEN).toContain("opacity-0");
    expect(LABEL_HIDDEN).toContain("group-hover/side:opacity-100");
    expect(v.className).toContain(LABEL_HIDDEN);
  });

  it("a click on the version does not fold the sidebar", async () => {
    wrap(<DesktopSidebar user={admin} />);
    fireEvent.click(await screen.findByRole("link", { name: /MegooColab 0\.23\.1/ }));
    expect(aside()).toHaveAttribute("data-collapsed", "false");
  });
});
