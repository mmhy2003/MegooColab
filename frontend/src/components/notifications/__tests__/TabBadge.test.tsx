import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TabBadge } from "@/components/notifications/TabBadge";
import { setFaviconBadge } from "@/lib/favicon";
import { setTitleCount } from "@/lib/title";

vi.mock("next/navigation", () => ({ usePathname: () => "/projects" }));
vi.mock("@/lib/favicon", () => ({ setFaviconBadge: vi.fn() }));
vi.mock("@/lib/title", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/title")>()), setTitleCount: vi.fn() }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

const marked = () => [vi.mocked(setFaviconBadge).mock.lastCall?.[0], vi.mocked(setTitleCount).mock.lastCall?.[0]];

describe("TabBadge", () => {
  it("marks the tab while anything is unread, and clears it when it goes", async () => {
    let count = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url === "/api/notifications/unread-count" ? new Response(JSON.stringify({ count }), { status: 200 }) : new Response(null, { status: 404 }),
      ),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const refresh = (n: number) => {
      count = n;
      return act(() => client.invalidateQueries({ queryKey: ["notifications", "count"] }));
    };
    const { unmount } = render(
      <QueryClientProvider client={client}>
        <TabBadge />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(marked()).toEqual([false, 0]));

    await refresh(2);
    await waitFor(() => expect(marked()).toEqual([true, 2]));

    await refresh(0);
    await waitFor(() => expect(marked()).toEqual([false, 0]));

    await refresh(5);
    await waitFor(() => expect(marked()).toEqual([true, 5]));
    unmount();
    expect(marked()).toEqual([false, 0]);
  });
});
