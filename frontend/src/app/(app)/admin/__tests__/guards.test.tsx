import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminAgentsPage from "@/app/(app)/admin/agents/page";
import AuditPage from "@/app/(app)/admin/audit/page";
import AdminSettingsPage from "@/app/(app)/admin/settings/page";
import UsersPage from "@/app/(app)/admin/users/page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/admin",
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe.each([
  ["Agents", AdminAgentsPage],
  ["Audit", AuditPage],
  ["Settings", AdminSettingsPage],
  ["Users", UsersPage],
])("admin %s page", (_name, Page) => {
  it("tells a member they can't, and asks the server for nothing else", async () => {
    const fetchMock = vi.fn(async (url: string) =>
      new Response(JSON.stringify(url === "/api/auth/me" ? { user: { id: "u1", name: "M", email: "m@x.io", role: "member" } } : [])),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Page />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("You don't have permission to do that.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([u]) => u)).toEqual(["/api/auth/me"]);
  });
});
