import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
  it("closes the user menu on a click outside it", () => {
    renderHeader();
    fireEvent.click(screen.getByRole("button", { name: /Ahmed/ }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.click(document.querySelector("[data-backdrop]")!);
    expect(screen.queryByRole("menu")).toBeNull();
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
