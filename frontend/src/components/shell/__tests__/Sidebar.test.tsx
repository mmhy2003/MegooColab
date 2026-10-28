import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Sidebar } from "@/components/shell/Sidebar";
import type { User } from "@/lib/types";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

const member = { id: "u1", name: "Mona", email: "m@x.io", role: "member" } as User;
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

function mockFetch(handler: (url: string) => Response | undefined) {
  const fetchMock = vi.fn(async (url: string) => handler(url) ?? new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Sidebar", () => {
  it("puts Dashboard first with the need-you badge", async () => {
    mockFetch((url) => (url === "/api/dashboard/count" ? json({ needs_you: 3 }) : undefined));
    wrap(<Sidebar user={member} />);
    const nav = within(screen.getByRole("navigation", { name: "Main" })).getAllByRole("link").slice(1); // [0] is the logo
    expect(nav[0]).toHaveAttribute("href", "/");
    expect(nav[0]).toHaveAttribute("aria-current", "page");
    expect(await within(nav[0]).findByLabelText("3 need you")).toHaveTextContent("3");
  });

  it("shows no badge at zero", async () => {
    const fetchMock = mockFetch((url) => (url === "/api/dashboard/count" ? json({ needs_you: 0 }) : undefined));
    wrap(<Sidebar user={member} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/dashboard/count", expect.anything()));
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument(); // no badge in the name
  });
});
