import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "p" }),
  usePathname: () => "/memory/entity/p",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import MemoryEntityPage from "@/app/(app)/memory/entity/[id]/page";
import { EntityList } from "@/components/memory/EntityList";
import { memKeys, type MemEntity } from "@/lib/memory";
import { useShownTrail } from "@/lib/trail";

const ENTS: MemEntity[] = [
  { id: "o", kind: "org", name: "Organization", description: "", conclusion_count: 3 },
  { id: "p", kind: "project", name: "PAY — Payments", description: "", conclusion_count: 5 },
  { id: "w", kind: "project", name: "WEB — Web", description: "", conclusion_count: 2 },
  { id: "a", kind: "agent", name: "laptop-claude", description: "", conclusion_count: 9 },
];

function Probe() {
  const trail = useShownTrail("/memory/entity/p");
  return <p data-testid="trail">{trail.crumbs.map((c) => `${c.label ?? "…"}${c.href ? `(${c.href})` : ""}`).join(" › ")}</p>;
}

function show() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = url === "/api/memory/entities"
        ? ENTS
        : url === "/api/memory/entities/p"
          ? { entity: ENTS[1], cards: [] }
          : url.startsWith("/api/memory/entities/p/conclusions")
            ? { items: [], next_cursor: null }
            : url === "/api/auth/me"
              ? { user: { id: "u1", name: "M", email: "m@x.io", role: "member" } }
              : [];
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryEntityPage />
      <Probe />
    </QueryClientProvider>,
  );
}

beforeEach(() => sessionStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the Memory reader", () => {
  it("the entity list sits beside the entity, grouped, with the current one marked", async () => {
    show();
    const list = await screen.findByRole("complementary", { name: "Entities" });
    const current = await within(list).findByRole("link", { name: /PAY — Payments/ });
    expect(current).toHaveAttribute("aria-current", "page");
    expect(within(list).getByRole("link", { name: /WEB — Web/ })).toHaveAttribute("href", "/memory/entity/w");
    expect(within(list).getByRole("link", { name: /laptop-claude/ })).not.toHaveAttribute("aria-current");
    expect(within(list).getAllByRole("heading").map((h) => h.textContent)).toEqual(["Organization", "Projects", "Agents"]);
    await waitFor(() => expect(screen.getByTestId("trail")).toHaveTextContent("Memory(/memory) › Projects › PAY — Payments"));
    expect(screen.getByRole("link", { name: "← Back to Memory" })).toHaveAttribute("href", "/memory");
  });

  it("the filter is shared with the Memory page and kept for the tab", async () => {
    show();
    const list = await screen.findByRole("complementary", { name: "Entities" });
    await within(list).findByRole("link", { name: /PAY — Payments/ });
    fireEvent.change(within(list).getByLabelText("Filter entities"), { target: { value: "web" } });
    expect(within(list).queryByRole("link", { name: /laptop-claude/ })).toBeNull();
    cleanup();
    render(<EntityList entities={ENTS} />);
    expect(screen.getByLabelText("Filter entities")).toHaveValue("web");
    expect(screen.queryByRole("link", { name: /laptop-claude/ })).toBeNull();
  });

  it("works when storage throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    show();
    const list = await screen.findByRole("complementary", { name: "Entities" });
    fireEvent.change(within(list).getByLabelText("Filter entities"), { target: { value: "web" } });
    expect(within(list).getByRole("link", { name: /WEB — Web/ })).toBeInTheDocument();
  });

  it("hopping to another entity keeps the list while it loads", () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Promise<Response>(() => {})));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    client.setQueryData(memKeys.entities("", ""), ENTS);
    render(
      <QueryClientProvider client={client}>
        <MemoryEntityPage />
        <Probe />
      </QueryClientProvider>,
    );
    const list = screen.getByRole("complementary", { name: "Entities" });
    expect(within(list).getByRole("link", { name: /PAY — Payments/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("trail")).toHaveTextContent("Memory(/memory) › Projects › PAY — Payments");
  });
});
