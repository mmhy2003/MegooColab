import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import HubPage from "@/app/(app)/hub/page";

let search = "";
const replace = vi.fn((url: string) => {
  search = url.split("?")[1] ?? "";
});
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => "/hub",
  useSearchParams: () => new URLSearchParams(search),
}));

const OWNER = { id: "u1", name: "Ada" };
const tool = (over: Record<string, unknown>) => ({
  id: "t1", kind: "mcp", name: "context7", description: "Reads docs", version: 1, rev: 1, owner: OWNER,
  is_copy: false, source_state: null, removed: false, secrets_missing: false, runs_code: false,
  read_only_safe: false, sharing: { teams: [], users: [], everyone: false }, ...over,
});

let shelves: Record<string, unknown[]>;
let fetchMock: ReturnType<typeof vi.fn<(url: string, init?: RequestInit) => Promise<Response>>>;

beforeEach(() => {
  search = "";
  shelves = {
    mine: [
      tool({}),
      tool({ id: "t2", kind: "skill", name: "ui-review", secrets_missing: true, source_state: "update_available",
        sharing: { teams: [{ id: "tm", name: "Platform" }], users: [], everyone: false } }),
    ],
    shared: [tool({ id: "t3", name: "sentry", owner: { id: "u2", name: "Mona" }, sharing: null })],
    everyone: [],
  };
  fetchMock = vi.fn(async (url: string) => {
    const u = new URL(url, "http://x");
    if (u.pathname === "/api/hub/tools") {
      const q = u.searchParams.get("q") ?? "";
      const rows = (shelves[u.searchParams.get("shelf") ?? "mine"] as { name: string }[]).filter((t) => t.name.includes(q));
      return new Response(JSON.stringify(rows));
    }
    return new Response(JSON.stringify([]));
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  replace.mockClear();
});

const renderPage = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <HubPage />
    </QueryClientProvider>,
  );

describe("Tool Hub page", () => {
  it("lists my tools with their state", async () => {
    renderPage();
    expect(await screen.findByRole("link", { name: /context7/ })).toHaveAttribute("href", "/hub/t1");
    expect(screen.getByRole("tab", { name: "Mine" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("key missing")).toBeInTheDocument();
    expect(screen.getByText("Update available")).toBeInTheDocument();
    expect(screen.getByText("Shared: Platform")).toBeInTheDocument();
    expect(screen.getByText("Private")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add MCP" })).toHaveAttribute("href", "/hub/new-mcp");
    expect(screen.getByRole("link", { name: "Add skill" })).toHaveAttribute("href", "/hub/new-skill");
  });

  it("switching to Shared with me fetches that shelf and names the owner", async () => {
    const view = renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Shared with me" }));
    view.rerender(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <HubPage />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("by Mona")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([u]) => u === "/api/hub/tools?shelf=shared")).toBe(true);
  });

  it("searching refetches with q", async () => {
    renderPage();
    await screen.findByRole("link", { name: /context7/ });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search tools" }), { target: { value: "ui" } });
    await waitFor(() => expect(screen.queryByRole("link", { name: /context7/ })).not.toBeInTheDocument());
    expect(fetchMock.mock.calls.some(([u]) => u === "/api/hub/tools?shelf=mine&q=ui")).toBe(true);
  });

  it("an empty shelf says so", async () => {
    search = "tab=everyone";
    renderPage();
    expect(await screen.findByText("Nothing shared with you yet.")).toBeInTheDocument();
  });

  it("an empty library says so", async () => {
    shelves.mine = [];
    renderPage();
    expect(await screen.findByText("Nothing here yet.")).toBeInTheDocument();
  });
});
