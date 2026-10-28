import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DeleteSprintButton } from "@/components/sprint/DeleteSprintButton";
import type { Sprint } from "@/lib/types";

const sprint = (state: Sprint["state"]) =>
  ({ id: "s1", name: "S1", state, start_date: "2026-11-02", end_date: "2026-11-13", goal: "" }) as Sprint;

function wrap(ui: ReactNode) {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  return invalidate;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("DeleteSprintButton", () => {
  it("deletes a sprint after saying where its tasks go", async () => {
    const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    const invalidate = wrap(<DeleteSprintButton sprint={sprint("planned")} taskCount={3} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete sprint S1" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveAccessibleName("Delete S1?");
    expect(dialog).toHaveTextContent("3 tasks go back to the backlog.");
    expect(dialog).not.toHaveTextContent("history");
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/sprints/s1", expect.objectContaining({ method: "DELETE" })));
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["sprints"] }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["tasks"] });
  });

  it("warns that an active sprint's history is lost", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
    wrap(<DeleteSprintButton sprint={sprint("active")} taskCount={1} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete sprint S1" }));
    expect(await screen.findByRole("alertdialog")).toHaveTextContent(
      "1 task goes back to the backlog. Its burndown and velocity history is lost.",
    );
  });
});
