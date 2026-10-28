import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Dashboard } from "@/components/dashboard/Dashboard";
import { SCOPE_KEY } from "@/lib/dashboard";
import type { User } from "@/lib/types";

import { dashboardFixture } from "./fixture";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const member = { id: "u1", name: "Mona", email: "m@x.io", role: "member" } as User;
const admin = { ...member, role: "admin" } as User;

function mockFetch() {
  const fetchMock = vi.fn(async (url: string) =>
    url.startsWith("/api/dashboard?") ? new Response(JSON.stringify(dashboardFixture()), { status: 200 }) : new Response(null, { status: 204 }),
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
});
