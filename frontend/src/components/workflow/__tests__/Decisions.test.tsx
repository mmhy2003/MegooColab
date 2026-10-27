import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Decisions } from "@/components/workflow/Decisions";

const decision = (id: string, step: number | null, extra: Record<string, unknown> = {}) => ({
  id,
  stage: step === null ? "done" : "build",
  step,
  decision: `Decision ${id}`,
  reason: `Because ${id}`,
  cost_if_wrong: `Cost ${id}`,
  plan_said: null,
  author: "Ann's Claude Code",
  created_at: "2026-10-27T10:00:00Z",
  ...extra,
});

function setup(decisions: unknown[]) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ decisions, test_runs: [], unverified_steps: [] }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <Decisions taskKey="PAY-1" />
    </QueryClientProvider>,
  );
  return { fetchMock, view };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Decisions", () => {
  it("groups by step and labels each field", async () => {
    setup([decision("a", 2, { plan_said: "Use a list" }), decision("b", 1), decision("c", null)]);
    const step2 = await screen.findByRole("region", { name: "Step 2" });
    expect(within(step2).getByText("Decision a")).toBeInTheDocument();
    expect(within(step2).getByText("Plan said")).toBeInTheDocument();
    expect(within(step2).getByText("Use a list")).toBeInTheDocument();
    expect(within(step2).getByText("Why")).toBeInTheDocument();
    expect(within(step2).getByText("Because a")).toBeInTheDocument();
    expect(within(step2).getByText("Cost if wrong")).toBeInTheDocument();
    expect(within(step2).getByText(/Ann's Claude Code/)).toBeInTheDocument();
    const step1 = screen.getByRole("region", { name: "Step 1" });
    expect(within(step1).queryByText("Plan said")).toBeNull(); // no plan_said, no label
    expect(screen.getByRole("region", { name: "Done" })).toHaveTextContent("Decision c");
    const headings = screen.getAllByRole("heading").map((h) => h.textContent);
    expect(headings).toEqual(["Step 1", "Step 2", "Done"]);
  });

  it("renders nothing when there are none", async () => {
    const { fetchMock, view } = setup([]);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(view.container).toBeEmptyDOMElement();
  });

  it("names a connected agent by its person", async () => {
    setup([decision("a", 1, { author: "Sam's connected agent" })]);
    expect(await screen.findByText(/Sam's connected agent/)).toBeInTheDocument();
  });
});
