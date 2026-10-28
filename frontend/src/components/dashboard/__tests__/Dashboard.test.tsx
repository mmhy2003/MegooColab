import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Dashboard } from "@/components/dashboard/Dashboard";
import { SCOPE_KEY } from "@/lib/dashboard";
import type { User } from "@/lib/types";

import { dashboardFixture, healthy } from "./fixture";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const member = { id: "u1", name: "Mona", email: "m@x.io", role: "member" } as User;
const admin = { ...member, role: "admin" } as User;

function mockFetch(body = dashboardFixture()) {
  const fetchMock = vi.fn(async (url: string) =>
    url.startsWith("/api/dashboard?") ? new Response(JSON.stringify(body), { status: 200 }) : new Response(null, { status: 204 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const dashboardCalls = (fetchMock: ReturnType<typeof mockFetch>) =>
  fetchMock.mock.calls.map(([u]) => u).filter((u) => u.startsWith("/api/dashboard?"));

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("Dashboard", () => {
  it("asks for My teams by default and remembers a new choice", async () => {
    const fetchMock = mockFetch();
    wrap(<Dashboard user={member} />);
    await screen.findByText("Refund flow for partial orders");
    expect(dashboardCalls(fetchMock)).toEqual(["/api/dashboard?scope=teams"]);
    expect(screen.getByRole("button", { name: "My teams" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Mine" }));
    await waitFor(() => expect(dashboardCalls(fetchMock)).toContain("/api/dashboard?scope=mine"));
    expect(localStorage.getItem(SCOPE_KEY)).toBe("mine");
  });

  it("starts with the remembered choice", async () => {
    localStorage.setItem(SCOPE_KEY, "mine");
    const fetchMock = mockFetch();
    wrap(<Dashboard user={member} />);
    await screen.findByText("Refund flow for partial orders");
    expect(dashboardCalls(fetchMock)).toEqual(["/api/dashboard?scope=mine"]);
  });

  it("offers Everything to admins only", async () => {
    mockFetch();
    wrap(<Dashboard user={member} />);
    await screen.findByText("Refund flow for partial orders");
    expect(screen.queryByRole("button", { name: "Everything" })).toBeNull();
    cleanup();
    wrap(<Dashboard user={admin} />);
    expect(await screen.findByRole("button", { name: "Everything" })).toBeInTheDocument();
  });

  it("refetches every 60 s for admins only", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = mockFetch();
    wrap(<Dashboard user={admin} />);
    await waitFor(() => expect(dashboardCalls(fetchMock)).toHaveLength(1));
    await act(() => vi.advanceTimersByTimeAsync(60_000));
    await waitFor(() => expect(dashboardCalls(fetchMock)).toHaveLength(2));
    cleanup();
    const memberFetch = mockFetch();
    wrap(<Dashboard user={member} />);
    await waitFor(() => expect(dashboardCalls(memberFetch)).toHaveLength(1));
    await act(() => vi.advanceTimersByTimeAsync(60_000));
    expect(dashboardCalls(memberFetch)).toHaveLength(1);
  });

  it("lays out every widget, and System only when the server sends it", async () => {
    mockFetch(dashboardFixture({ system: healthy }));
    wrap(<Dashboard user={admin} />);
    await screen.findByText("Refund flow for partial orders");
    for (const name of ["Needs you", "My tasks", "Running now", "Agents", "Workflows by stage", "Tasks finished · last 14 days", "Projects", "Recent activity", "System"]) {
      expect(screen.getByRole("region", { name })).toBeInTheDocument();
    }
    cleanup();
    mockFetch();
    wrap(<Dashboard user={member} />);
    await screen.findByText("Refund flow for partial orders");
    expect(screen.queryByRole("region", { name: "System" })).toBeNull();
  });

  it("keeps every frame while loading", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));
    wrap(<Dashboard user={member} />);
    expect(screen.getByRole("region", { name: "Projects" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Recent activity" })).toBeInTheDocument();
  });

  it("says so when the dashboard cannot load", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "boom" }), { status: 500 })));
    wrap(<Dashboard user={member} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The dashboard could not load.");
  });

  it("falls back to My teams when an admin loses the admin role", async () => {
    const fetchMock = mockFetch();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = render(<QueryClientProvider client={client}><Dashboard user={admin} /></QueryClientProvider>);
    await userEvent.click(await screen.findByRole("button", { name: "Everything" }));
    await waitFor(() => expect(dashboardCalls(fetchMock)).toContain("/api/dashboard?scope=all"));
    view.rerender(<QueryClientProvider client={client}><Dashboard user={member} /></QueryClientProvider>);
    expect(screen.getByRole("button", { name: "My teams" })).toHaveAttribute("aria-pressed", "true");
    expect(dashboardCalls(fetchMock).at(-1)).toBe("/api/dashboard?scope=teams");
  });
});
