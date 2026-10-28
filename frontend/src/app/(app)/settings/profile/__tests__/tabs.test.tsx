import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProfilePage from "@/app/(app)/settings/profile/page";

const replace = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/settings/profile",
  useSearchParams: () => new URLSearchParams(search),
}));

beforeEach(() => {
  search = "";
  replace.mockReset();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify({ user: { id: "u1", name: "Mona", email: "m@x.io", role: "member", totp_enabled: false } })),
    ),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const renderPage = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ProfilePage />
    </QueryClientProvider>,
  );

describe("Profile tabs", () => {
  it("has Name, Password and Two-factor sign-in tabs, Name first", async () => {
    renderPage();
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Name", "Password", "Two-factor sign-in"]);
    expect(screen.getByRole("tabpanel", { name: "Name" })).toBeVisible();
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
  });

  it("opens the tab the address names, and puts a chosen one there", async () => {
    search = "tab=password";
    renderPage();
    expect(await screen.findByRole("tabpanel", { name: "Password" })).toBeVisible();
    expect(screen.getByLabelText("Current password")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Two-factor sign-in" }));
    expect(replace).toHaveBeenCalledWith("/settings/profile?tab=two-factor", { scroll: false });
  });
});
