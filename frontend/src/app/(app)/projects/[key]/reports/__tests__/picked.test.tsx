import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ReportsPage from "@/app/(app)/projects/[key]/reports/page";
import { project } from "@/components/project/__tests__/fixture";
import { qk } from "@/lib/queries";
import type { Sprint } from "@/lib/types";

vi.mock("next/navigation", () => ({ useParams: () => ({ key: "PAY" }) }));
vi.mock("@/components/sprint/BurndownChart", () => ({ BurndownChart: ({ sprintName }: { sprintName: string }) => <p>Burndown of {sprintName}</p> }));
vi.mock("@/components/sprint/VelocityChart", () => ({ VelocityChart: () => null }));

const done = (id: string, name: string) =>
  ({ id, name, state: "completed", start_date: "2026-10-01", end_date: "2026-10-14", goal: "" }) as Sprint;

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/projects/PAY") return new Response(JSON.stringify(project()));
      if (url === "/api/projects/PAY/sprints") return new Response(JSON.stringify([done("s1", "S1"), done("s2", "S2")]));
      if (url === "/api/auth/me") return new Response(JSON.stringify({ user: { id: "u1", name: "M", email: "m@x.io", role: "manager" } }));
      return new Response(JSON.stringify([]));
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Reports after a sprint is deleted", () => {
  it("falls back to another sprint when the picked one is gone", async () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <ReportsPage />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Burndown of S2")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Sprint" }), "s1");
    expect(screen.getByText("Burndown of S1")).toBeInTheDocument();
    act(() => client.setQueryData(qk.sprints("PAY"), [done("s2", "S2")])); // S1 was deleted
    await waitFor(() => expect(screen.getByText("Burndown of S2")).toBeInTheDocument());
    expect(screen.queryByText("No sprint has started yet.")).toBeNull();
  });
});
