import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminUsersPage, { lastSignIn } from "@/app/(app)/admin/users/page";

const ME = { id: "me", name: "Root Admin", email: "root@acme.io", role: "admin", status: "active" };
const BEA = { id: "bea", name: "Bea Lopez", email: "bea@acme.io", role: "viewer", status: "active" };
const CY = { id: "cy", name: "Cy Ng", email: "cy@acme.io", role: "manager", status: "active" };
const DEE = { id: "dee", name: "Dee Moss", email: "dee@acme.io", role: "viewer", status: "invited" };
const ELI = { id: "eli", name: "Eli Kent", email: "eli@acme.io", role: "member", status: "deactivated" };
const DETAILS = [
  { user_id: "me", totp: true, passkeys: 1, last_login_at: new Date().toISOString() },
  { user_id: "bea", totp: false, passkeys: 2, last_login_at: "2026-10-01T10:00:00Z" },
  { user_id: "cy", totp: false, passkeys: 0, last_login_at: "2026-10-01T10:00:00Z" },
  { user_id: "dee", totp: false, passkeys: 0, last_login_at: null },
  { user_id: "eli", totp: false, passkeys: 0, last_login_at: null },
];

type Call = { method: string; url: string; body?: unknown };

function setup() {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (method !== "GET") {
      calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (url.endsWith("/reset-link")) return new Response(JSON.stringify({ reset_url: "http://x/reset/abc" }), { status: 201 });
      if (method === "PATCH") return new Response(JSON.stringify({ user: BEA }), { status: 200 });
      return new Response(null, { status: 204 });
    }
    if (url === "/api/auth/me") return new Response(JSON.stringify({ user: ME }), { status: 200 });
    if (url === "/api/admin/users/details") return new Response(JSON.stringify(DETAILS), { status: 200 });
    return new Response(JSON.stringify([ME, BEA, CY, DEE, ELI]), { status: 200 });
  }));
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AdminUsersPage />
    </QueryClientProvider>,
  );
  return calls;
}

async function openMenu(name: string) {
  await userEvent.click(await screen.findByRole("button", { name: `Actions for ${name}` }));
  return screen.findByRole("menu");
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AdminUsersPage", () => {
  it("sends the role that was picked, not the one shown before", async () => {
    const calls = setup();
    const select = await screen.findByRole("combobox", { name: "Role of Bea Lopez" });
    expect(select).toHaveValue("viewer");
    fireEvent.change(select, { target: { value: "member" } });
    await waitFor(() => expect(calls).toEqual([{ method: "PATCH", url: "/api/admin/users/bea", body: { role: "member" } }]));
  });

  it("shows how each person's two-factor sign-in is set up, and their last sign-in", async () => {
    setup();
    const row = (await screen.findByText("bea@acme.io")).closest("tr")!;
    expect(row).toHaveTextContent("On");
    expect(row).toHaveTextContent("2 passkeys");
    const own = screen.getByText("root@acme.io").closest("tr")!;
    expect(own).toHaveTextContent("App + 1 passkey");
    expect(own).toHaveTextContent("you");
    expect(screen.getByText("cy@acme.io").closest("tr")).toHaveTextContent("Off");
    expect(screen.getByText("dee@acme.io").closest("tr")).toHaveTextContent("Never");
  });

  it("the user card labels two-factor and last seen", async () => {
    setup();
    const row = (await screen.findByText("cy@acme.io")).closest("tr")!;
    expect(row).toHaveTextContent("Two-factor: Off");
    expect(screen.getByText("dee@acme.io").closest("tr")).toHaveTextContent("Last seen: Never");
  });

  it("filters by status, by two-factor and by a search", async () => {
    setup();
    await screen.findByText("bea@acme.io");
    await userEvent.click(screen.getByRole("button", { name: "Invited 1" }));
    expect(screen.queryByText("bea@acme.io")).toBeNull();
    expect(screen.getByText("dee@acme.io")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Two-factor off 3" }));
    expect(screen.getAllByRole("row").slice(1).map((r) => within(r).getByText(/@acme\.io/).textContent)).toEqual([
      "cy@acme.io", "dee@acme.io", "eli@acme.io",
    ]);
    await userEvent.click(screen.getByRole("button", { name: "All 5" }));
    await userEvent.type(screen.getByRole("searchbox", { name: "Search people" }), "lopez");
    expect(screen.getAllByRole("row").slice(1)).toHaveLength(1);
  });

  it("offers only what applies to each person, and nothing on oneself", async () => {
    setup();
    await screen.findByText("bea@acme.io");
    expect(screen.queryByRole("button", { name: "Actions for Root Admin" })).toBeNull();
    let menu = await openMenu("Bea Lopez");
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual([
      "Copy a password-reset link", "Turn off two-factor sign-in", "Deactivate", "Delete…",
    ]);
    await userEvent.keyboard("{Escape}");
    menu = await openMenu("Dee Moss");
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual([
      "Copy a new invite link", "Deactivate", "Delete…",
    ]);
    await userEvent.keyboard("{Escape}");
    menu = await openMenu("Eli Kent");
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual([
      "Copy a password-reset link", "Reactivate", "Delete…",
    ]);
  });

  it("turns off someone's two-factor sign-in after asking", async () => {
    const calls = setup();
    await userEvent.click(within(await openMenu("Bea Lopez")).getByRole("menuitem", { name: "Turn off two-factor sign-in" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Turn off two-factor sign-in for Bea Lopez?");
    await userEvent.click(within(dialog).getByRole("button", { name: "Turn off" }));
    await waitFor(() => expect(calls).toEqual([{ method: "POST", url: "/api/admin/users/bea/reset-two-factor" }]));
  });

  it("deletes someone once their email is typed", async () => {
    const calls = setup();
    await userEvent.click(within(await openMenu("Cy Ng")).getByRole("menuitem", { name: "Delete…" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete Cy Ng?" });
    expect(dialog).toHaveTextContent("This can't be undone.");
    expect(dialog).toHaveTextContent("Deleted with them");
    expect(dialog).toHaveTextContent("Kept for the team");
    const del = within(dialog).getByRole("button", { name: "Delete" });
    expect(del).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText("Type cy@acme.io to confirm"), "CY@acme.io");
    await userEvent.click(del);
    await waitFor(() => expect(calls).toEqual([{ method: "DELETE", url: "/api/admin/users/cy" }]));
  });

  it("deactivating still asks first", async () => {
    const calls = setup();
    await userEvent.click(within(await openMenu("Cy Ng")).getByRole("menuitem", { name: "Deactivate" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(calls).toEqual([{ method: "POST", url: "/api/admin/users/cy/deactivate" }]));
  });
});

describe("lastSignIn", () => {
  const now = new Date("2026-10-31T15:00:00");
  it.each([
    [null, "Never"],
    ["2026-10-31T09:12:00", "Today, 09:12"],
    ["2026-10-30T20:00:00", "Yesterday"],
    ["2026-10-28T10:00:00", "3 days ago"],
  ])("%s → %s", (iso, text) => expect(lastSignIn(iso, now)).toBe(text));

  it("names the date when it was long ago", () => {
    expect(lastSignIn("2026-08-01T10:00:00", now)).toBe(new Date("2026-08-01T10:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }));
  });
});
