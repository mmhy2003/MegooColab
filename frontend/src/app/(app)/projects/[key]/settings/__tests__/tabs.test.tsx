import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProjectSettingsPage from "@/app/(app)/projects/[key]/settings/page";
import { project } from "@/components/project/__tests__/fixture";

const replace = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useParams: () => ({ key: "PAY" }),
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => "/projects/PAY/settings",
  useSearchParams: () => new URLSearchParams(search),
}));

beforeEach(() => {
  search = "";
  replace.mockReset();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/projects/PAY") return new Response(JSON.stringify(project()));
      if (url === "/api/auth/me") return new Response(JSON.stringify({ user: { id: "u1", name: "M", email: "m@x.io", role: "manager" } }));
      return new Response(JSON.stringify([]));
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const renderPage = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ProjectSettingsPage />
    </QueryClientProvider>,
  );

describe("Project settings tabs", () => {
  it("uses the same underline tabs as the admin pages, General first", async () => {
    renderPage();
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["General", "Columns", "Repositories", "Labels", "Workflow"]);
    expect(screen.getByRole("tablist", { name: "Settings sections" })).toHaveClass("border-b");
    expect(screen.getByRole("tab", { name: "General" })).toHaveAttribute("aria-selected", "true");
  });

  it("opens the tab the address names, and puts a chosen one there", async () => {
    search = "tab=labels";
    renderPage();
    expect(await screen.findByLabelText("Label name")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Columns" }));
    expect(replace).toHaveBeenCalledWith("/projects/PAY/settings?tab=columns", { scroll: false });
  });
});
