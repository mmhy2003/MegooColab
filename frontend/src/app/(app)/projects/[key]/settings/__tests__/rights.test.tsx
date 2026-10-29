import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ProjectSettingsPage from "@/app/(app)/projects/[key]/settings/page";
import { project } from "@/components/project/__tests__/fixture";

let search = "";
vi.mock("next/navigation", () => ({
  useParams: () => ({ key: "PAY" }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/projects/PAY/settings",
  useSearchParams: () => new URLSearchParams(search),
}));

function setup(role: string, status = "active") {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body =
        url === "/api/projects/PAY" ? { ...project(), status }
        : url === "/api/auth/me" ? { user: { id: "u1", name: "M", email: "m@x.io", role } }
        : url === "/api/projects/PAY/columns" ? [{ id: "c1", name: "To Do", category: "before", position: 0, task_count: 0 }]
        : url === "/api/projects/PAY/repositories" ? [{ id: "r1", name: "pay", url: "https://g/pay", provider: "github", default_branch: "main", connection: null }]
        : url === "/api/projects/PAY/labels" ? [{ id: "l1", name: "urgent", color: "#ff0000" }]
        : [];
      return new Response(JSON.stringify(body));
    }),
  );
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ProjectSettingsPage />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  search = "";
});

// hidden panels stay mounted; aria-labelledby names cannot be resolved for them, so find them by id
const panel = (name: string) => within(document.getElementById(`panel-${name.toLowerCase()}`)!);

async function expectReadOnly() {
  await screen.findByRole("tab", { name: "General" });
  await screen.findByText("urgent");
  expect(panel("General").queryByRole("button", { name: "Save" })).toBeNull();
  expect(panel("General").queryByLabelText("Name")).toBeNull();
  expect(panel("Columns").queryByRole("button", { name: "Add column", hidden: true })).toBeNull();
  expect(panel("Columns").queryByRole("button", { name: "Delete To Do", hidden: true })).toBeNull();
  expect(panel("Repositories").queryByRole("button", { name: "Add", hidden: true })).toBeNull();
  expect(panel("Repositories").queryByRole("button", { name: "Remove pay", hidden: true })).toBeNull();
  expect(panel("Labels").queryByRole("button", { name: "Add label", hidden: true })).toBeNull();
  expect(panel("Labels").queryByRole("button", { name: "Delete label urgent", hidden: true })).toBeNull();
}

describe("Project settings rights", () => {
  it("a member sees the settings read-only", async () => {
    setup("member");
    await expectReadOnly();
    expect(panel("General").getByText(project().name)).toBeInTheDocument();
  });

  it("a manager of an archived project sees them read-only but can still reopen it", async () => {
    setup("manager", "archived");
    await expectReadOnly();
    expect(panel("General").getByRole("button", { name: "Active" })).toBeEnabled();
  });

  it("a manager of an active project can edit everything", async () => {
    setup("manager");
    await screen.findByText("urgent");
    expect(panel("General").getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(panel("Columns").getByRole("button", { name: "Add column", hidden: true })).toBeInTheDocument();
    expect(panel("Repositories").getByRole("button", { name: "Add", hidden: true })).toBeInTheDocument();
    expect(panel("Labels").getByRole("button", { name: "Add label", hidden: true })).toBeInTheDocument();
  });
});
