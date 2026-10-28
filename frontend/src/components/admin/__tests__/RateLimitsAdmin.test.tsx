import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RateLimitsAdmin } from "@/components/admin/RateLimitsAdmin";

function show(working: boolean) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ working }), { status: 200 })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RateLimitsAdmin />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("RateLimitsAdmin", () => {
  it("says the limits are working", async () => {
    show(true);
    expect(await screen.findByText("Working")).toHaveClass("text-cyan-ink");
    expect(screen.getByRole("region", { name: "Rate limits" })).toBeInTheDocument();
  });

  it("says plainly when the limits are off", async () => {
    show(false);
    expect(await screen.findByText("Valkey is unreachable — limits are off")).toHaveClass("text-pink");
  });
});
