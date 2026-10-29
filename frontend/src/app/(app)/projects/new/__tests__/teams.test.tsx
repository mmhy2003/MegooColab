import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import NewProjectPage from "@/app/(app)/projects/new/page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/projects/new",
  useSearchParams: () => new URLSearchParams(),
}));

const TEAMS = [{ id: "t1", name: "Core", is_member: false }];
const ADMIN = { user: { id: "u1", name: "A", email: "a@x.io", role: "admin" } };

function setup(me: Promise<unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => new Response(JSON.stringify(url === "/api/auth/me" ? await me : url === "/api/teams" ? TEAMS : []))),
  );
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <NewProjectPage />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("New project teams", () => {
  it("does not say to create a team while it is still learning who you are", async () => {
    setup(new Promise(() => {}));
    await new Promise((r) => setTimeout(r, 50)); // the team list has arrived
    expect(screen.queryByText("Create a team first.")).toBeNull();
  });

  it("offers an admin every team", async () => {
    setup(Promise.resolve(ADMIN));
    expect(await screen.findByRole("checkbox", { name: "Core" })).toBeInTheDocument();
    expect(screen.queryByText("Create a team first.")).toBeNull();
  });
});
