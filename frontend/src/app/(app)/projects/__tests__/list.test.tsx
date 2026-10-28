import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProjectsPage from "@/app/(app)/projects/page";
import { project } from "@/components/project/__tests__/fixture";
import { SHOW_ARCHIVED_KEY } from "@/lib/projectStatus";

const me = { user: { id: "u1", name: "M", email: "m@x.io", role: "member" } };

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/auth/me") return new Response(JSON.stringify(me));
      if (url === "/api/projects") {
        return new Response(
          JSON.stringify([
            project(),
            project({ id: "p2", key: "OLD", name: "Old site", status: "finished" }),
            project({ id: "p3", key: "ARC", name: "Archive me", status: "archived" }),
          ]),
        );
      }
      return new Response(null, { status: 204 });
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ProjectsPage />
    </QueryClientProvider>,
  );
}

describe("Projects list", () => {
  it("hides archived projects until Show archived is on, and remembers it", async () => {
    renderPage();
    expect(await screen.findByText("Payments")).toBeInTheDocument();
    expect(screen.getByText("Old site")).toBeInTheDocument();
    expect(screen.getByText("Finished")).toBeInTheDocument();
    expect(screen.queryByText("Archive me")).toBeNull();
    await userEvent.click(screen.getByRole("checkbox", { name: "Show archived" }));
    expect(screen.getByText("Archive me")).toBeInTheDocument();
    expect(screen.getByText("Archived")).toBeInTheDocument();
    expect(localStorage.getItem(SHOW_ARCHIVED_KEY)).toBe("true");
    cleanup();
    renderPage();
    expect(await screen.findByText("Archive me")).toBeInTheDocument();
  });
});
