import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminHubPage from "@/app/(app)/admin/hub/page";
import { answer } from "@/test/answer";

let role = "admin";
let rows: unknown[];
let fetchMock: ReturnType<typeof vi.fn<(url: string, init?: RequestInit) => Promise<Response>>>;

const ROW = {
  id: "t1", kind: "mcp", name: "ctx", description: "Reads docs", version: 1, rev: 1, owner: { id: "u2", name: "Mona" },
  is_copy: false, source_state: null, removed: false, secrets_missing: false, runs_code: false, read_only_safe: false,
  sharing: { teams: [{ id: "tm", name: "Platform" }], users: [], everyone: true },
};

beforeEach(() => {
  role = "admin";
  rows = [ROW];
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/auth/me") return new Response(JSON.stringify({ user: { id: "u1", name: "Ada", email: "a@x.io", role } }));
    if (url.startsWith("/api/admin/hub/tools") && !init?.method) return new Response(JSON.stringify(rows));
    if (init?.method === "POST") {
      rows = [];
      return new Response(null, { status: 204 });
    }
    return new Response(JSON.stringify([]));
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const renderPage = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AdminHubPage />
    </QueryClientProvider>,
  );

describe("admin Tool Hub", () => {
  it("lists shared tools with who sees them", async () => {
    renderPage();
    expect(await screen.findByText("ctx")).toBeInTheDocument();
    expect(screen.getByText("by Mona")).toBeInTheDocument();
    expect(screen.getByText("Everyone, Platform")).toBeInTheDocument();
  });

  it("Remove asks first, then removes and refreshes", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Remove ctx" }));
    expect(await screen.findByText(/Everyone who added it sees “removed by an admin”/)).toBeInTheDocument();
    await answer("Remove");
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u, i]) => u === "/api/admin/hub/tools/t1/remove" && i?.method === "POST")).toBe(true),
    );
    expect(await screen.findByText("Nothing is shared beyond its owner.")).toBeInTheDocument();
  });

  it("Stop sharing asks first", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Stop sharing ctx" }));
    await answer("Stop sharing");
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u, i]) => u === "/api/admin/hub/tools/t1/unshare" && i?.method === "POST")).toBe(true),
    );
  });

  it("a non-admin sees the permission card", async () => {
    role = "member";
    renderPage();
    expect(await screen.findByText("You don't have permission to do that.")).toBeInTheDocument();
  });
});
