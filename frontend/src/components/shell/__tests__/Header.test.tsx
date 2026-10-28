import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Header } from "@/components/shell/Header";
import type { User } from "@/lib/types";

vi.mock("next/navigation", () => ({ usePathname: () => "/projects", useRouter: () => ({ push: vi.fn() }) }));

const user = { id: "u1", name: "Ahmed", email: "a@x.io", role: "member" } as User;

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ count: 0 }), { status: 200 })));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderHeader() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Header user={user} onMenu={() => {}} />
    </QueryClientProvider>,
  );
}

describe("Header", () => {
  it("closes the user menu on a click outside it, with the page blurred while open", async () => {
    renderHeader();
    await userEvent.click(screen.getByRole("button", { name: /Ahmed/ }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.getAllByRole("menuitem").map((i) => i.textContent?.trim())).toEqual([
      "Profile", "Access tokens", "My agents", "Notifications", "Sign out",
    ]);
    await userEvent.click(document.querySelector("[data-backdrop]")!);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.querySelector("[data-backdrop]")).toBeNull();
  });

  it("works from the keyboard: arrows move, Escape closes and returns focus", async () => {
    renderHeader();
    const trigger = screen.getByRole("button", { name: /Ahmed/ });
    trigger.focus();
    await userEvent.keyboard("{Enter}");
    const items = screen.getAllByRole("menuitem");
    await userEvent.keyboard("{ArrowDown}");
    expect(items).toContain(document.activeElement);
    const first = document.activeElement;
    await userEvent.keyboard("{ArrowDown}");
    expect(document.activeElement).not.toBe(first);
    expect(items).toContain(document.activeElement);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("closes the notification panel on a click outside it and on Escape", () => {
    renderHeader();
    const bell = screen.getByRole("button", { name: "Notifications" });
    fireEvent.click(bell);
    expect(screen.getByRole("dialog", { name: "Notifications" })).toBeInTheDocument();
    fireEvent.click(document.querySelector("[data-backdrop]")!);
    expect(screen.queryByRole("dialog", { name: "Notifications" })).toBeNull();
    fireEvent.click(bell);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Notifications" })).toBeNull();
  });
});
