import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useMarkAllRead, useMarkRead } from "@/lib/notifications";

afterEach(() => vi.unstubAllGlobals());

function setup() {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { invalidate, wrapper };
}

// marking read sends no live event: everything that counts unread mentions refreshes here
describe("marking notifications read", () => {
  it("refreshes the bell, the dashboard and its badge for one", async () => {
    const { invalidate, wrapper } = setup();
    const { result } = renderHook(() => useMarkRead(), { wrapper });
    result.current.mutate("n1");
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["dashboard-count"] }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["notifications"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["dashboard"] });
  });

  it("and for all", async () => {
    const { invalidate, wrapper } = setup();
    const { result } = renderHook(() => useMarkAllRead(), { wrapper });
    result.current.mutate();
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["dashboard-count"] }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["notifications"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["dashboard"] });
  });
});
