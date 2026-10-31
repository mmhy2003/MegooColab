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

describe("Turning off someone's two-factor sign-in", () => {
  const CY = { id: "cy", name: "Cy", email: "cy@acme.io", role: "member", status: "active" };

  function setup(twoFactor: string[]) {
    const posts: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posts.push(url);
        return new Response(null, { status: 204 });
      }
      if (url === "/api/auth/me") return new Response(JSON.stringify({ user: ME }), { status: 200 });
      if (url === "/api/admin/users/two-factor") return new Response(JSON.stringify({ user_ids: twoFactor }), { status: 200 });
      return new Response(JSON.stringify([ME, BEA, CY]), { status: 200 });
    }));
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <AdminUsersPage />
      </QueryClientProvider>,
    );
    return posts;
  }

  it("is offered only for people with it on, never on oneself", async () => {
    setup(["me", "bea"]);
    expect(await screen.findByRole("button", { name: "Turn off two-factor sign-in for Bea" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Turn off two-factor sign-in for Cy" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Turn off two-factor sign-in for Root Admin" })).toBeNull();
  });

  it("asks first, then turns it off", async () => {
    const posts = setup(["bea"]);
    fireEvent.click(await screen.findByRole("button", { name: "Turn off two-factor sign-in for Bea" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Turn off two-factor sign-in for Bea?");
    expect(dialog).toHaveTextContent("Their authenticator app and all their passkeys are removed.");
    fireEvent.click(screen.getByRole("button", { name: "Turn off" }));
    await waitFor(() => expect(posts).toEqual(["/api/admin/users/bea/reset-two-factor"]));
  });

  it("cancelling changes nothing", async () => {
    const posts = setup(["bea"]);
    fireEvent.click(await screen.findByRole("button", { name: "Turn off two-factor sign-in for Bea" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await new Promise((r) => setTimeout(r, 20));
    expect(posts).toEqual([]);
  });
});
