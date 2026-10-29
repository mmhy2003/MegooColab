import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import TeamPage from "@/app/(app)/teams/[id]/page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "t1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

function setup(projectCount: number) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body =
        url === "/api/auth/me" ? { user: { id: "u1", name: "Admin", email: "a@x.io", role: "admin" } }
        : url === "/api/teams/t1" ? { id: "t1", name: "Core", description: "", members: [], projects: [], agents: [], project_count: projectCount }
        : [];
      return new Response(JSON.stringify(body));
    }),
  );
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TeamPage />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Delete team", () => {
  it("waits until the team has no projects, and says why", async () => {
    setup(1);
    const button = await screen.findByRole("button", { name: "Delete team" });
    expect(button).toBeDisabled();
    expect(screen.getByText("Move or delete this team's projects first.")).toBeInTheDocument();
    expect(button).toHaveAccessibleDescription("Move or delete this team's projects first.");
  });

  it("is offered once the team has none", async () => {
    setup(0);
    expect(await screen.findByRole("button", { name: "Delete team" })).toBeEnabled();
    expect(screen.queryByText("Move or delete this team's projects first.")).toBeNull();
  });
});
