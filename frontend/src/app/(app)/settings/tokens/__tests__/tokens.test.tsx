import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import TokensPage from "@/app/(app)/settings/tokens/page";

const BASE = { prefix: "mgc_abcd", expires_at: null, last_used_at: null, created_at: "2026-10-01T00:00:00Z", revoked_at: null };
const YOGA = {
  ...BASE, id: "t-yoga", name: "Yoga", scopes: ["runner", "mcp"],
  agents: [{ id: "a1", name: "Yoga Claude" }, { id: "a2", name: "Yoga Codex" }],
};
const SOLO = { ...BASE, id: "t-solo", name: "Solo", scopes: ["runner"], agents: [{ id: "a3", name: "Lone" }] };
const MCP = { ...BASE, id: "t-mcp", name: "Editor", scopes: ["mcp"], agents: [] };

function renderPage() {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([YOGA, SOLO, MCP]), { status: 200 })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TokensPage />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("TokensPage", () => {
  it("shows the agents linked to each token", async () => {
    renderPage();
    expect(await screen.findByText("Yoga Claude, Yoga Codex")).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Agents" })).toBeTruthy();
  });

  it("warns how many agents a revoke unlinks", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Revoke Yoga" }));
    expect(await screen.findByText(/2 linked agents will be unlinked and stay offline until you link them again\./)).toBeTruthy();
  });

  it("uses the singular for one agent, and says nothing for none", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Revoke Solo" }));
    expect(await screen.findByText(/1 linked agent will be unlinked/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Revoke Editor" }));
    expect(await screen.findByText(/Anything using it stops working\./)).toBeTruthy();
    expect(screen.queryByText(/will be unlinked/)).toBeNull();
  });
});
