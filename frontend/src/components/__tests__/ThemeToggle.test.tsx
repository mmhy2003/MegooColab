import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeToggle } from "@/components/ThemeToggle";

function mockSystemDark(dark: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: dark && query.includes("dark"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

describe("ThemeToggle", () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
    mockSystemDark(true);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("cycles system → dark → light → system and sets data-theme", () => {
    render(<ThemeToggle />);
    const button = screen.getByRole("button", { name: /theme: system/i });
    expect(document.documentElement.dataset.theme).toBe("dark"); // system is dark

    fireEvent.click(button);
    expect(screen.getByRole("button", { name: /theme: dark/i })).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe("dark");

    fireEvent.click(button);
    expect(screen.getByRole("button", { name: /theme: light/i })).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("megoo-theme")).toBe("light");

    fireEvent.click(button);
    expect(screen.getByRole("button", { name: /theme: system/i })).toBeInTheDocument();
  });

  it("survives localStorage throwing", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button", { name: /theme: system/i }));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
