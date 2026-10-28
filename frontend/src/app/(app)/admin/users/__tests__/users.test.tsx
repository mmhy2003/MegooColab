import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminUsersPage from "@/app/(app)/admin/users/page";

const ME = { id: "me", name: "Root Admin", email: "root@acme.io", role: "admin", status: "active" };
const BEA = { id: "bea", name: "Bea", email: "bea@acme.io", role: "viewer", status: "active" };

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AdminUsersPage", () => {
  it("sends the role that was picked, not the one shown before", async () => {
    const patches: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        patches.push(JSON.parse(String(init.body)));
        return new Response(JSON.stringify({ ...BEA, role: "member" }), { status: 200 });
      }
      if (url === "/api/auth/me") return new Response(JSON.stringify({ user: ME }), { status: 200 });
      return new Response(JSON.stringify([ME, BEA]), { status: 200 });
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <AdminUsersPage />
      </QueryClientProvider>,
    );
    const select = await screen.findByRole("combobox", { name: "Role of Bea" });
    expect(select).toHaveValue("viewer");
    fireEvent.change(select, { target: { value: "member" } });
    await waitFor(() => expect(patches).toEqual([{ role: "member" }]));
  });
});
