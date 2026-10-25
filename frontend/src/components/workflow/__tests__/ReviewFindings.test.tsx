import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReviewFindings, ReviewResult } from "@/components/workflow/ReviewFindings";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const findings = [
  { severity: "minor" as const, file: "b.py", line: null, summary: "rename" },
  { severity: "critical" as const, file: "a.py", line: 12, summary: "<img src=x onerror=alert(1)> leaks" },
  { severity: "minor" as const, file: null, line: null, summary: "typo" },
];

describe("ReviewFindings", () => {
  it("groups by severity, most severe first, with file:line as text", () => {
    const { container } = render(<ReviewFindings scope="step" step={2} round={1} verdict="changes_requested" findings={findings} />);
    const groups = screen.getAllByRole("heading").map((h) => h.textContent);
    expect(groups).toEqual(["Critical (1)", "Minor (2)"]);
    const critical = within(screen.getByRole("region", { name: "Critical findings" }));
    expect(critical.getByText("a.py:12")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Minor findings" })).getByText("b.py")).toBeInTheDocument();
    // summaries are text, never markup
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src=x onerror=alert\(1\)> leaks/)).toBeInTheDocument();
  });

  it("fetches the findings only when expanded", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ scope: "step", step: 2, round: 1, verdict: "changes_requested", findings }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ReviewResult taskKey="PAY-1" reviewId="r1" total={3} />
      </QueryClientProvider>,
    );
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Show findings (3)" }));
    expect(await screen.findByText("Critical (1)")).toBeInTheDocument();
    expect((fetchMock.mock.calls as unknown[][])[0]).toEqual(["/api/tasks/PAY-1/reviews/r1", expect.anything()]);
  });
});
