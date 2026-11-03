import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/admin/agents",
}));

import AdminAgentsPage from "@/app/(app)/admin/agents/page";

const AGENT = {
  id: "a1", name: "Mo's Claude Code", program: "claude_code", model: null, effort: null, status: "online",
  owner: { id: "u1", name: "Mo" }, machine: null, runner: null, current_run: null,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("admin agents", () => {
  it("on phones each agent is a card with labelled values", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        new Response(JSON.stringify(url === "/api/auth/me" ? { user: { id: "u1", role: "admin" } } : [AGENT]), { status: 200 }),
      ),
    );
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <AdminAgentsPage />
      </QueryClientProvider>,
    );
    const cell = (await screen.findByText("Mo's Claude Code")).closest("td")!;
    const table = cell.closest("table")!;
    expect(table).toHaveClass("max-md:block");
    expect(table.querySelector("thead")).toHaveClass("max-md:hidden");
    const labels = Array.from(cell.closest("tr")!.querySelectorAll("td")).map((td) => td.getAttribute("data-label"));
    expect(labels).toEqual(["Owner", "Agent", "Program", "Status", "Current run"]);
  });
});
