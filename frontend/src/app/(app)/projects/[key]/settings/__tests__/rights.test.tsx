import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ProjectSettingsPage from "@/app/(app)/projects/[key]/settings/page";
import { project } from "@/components/project/__tests__/fixture";
import type { Project } from "@/lib/types";

let search = "";
vi.mock("next/navigation", () => ({
  useParams: () => ({ key: "PAY" }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/projects/PAY/settings",
  useSearchParams: () => new URLSearchParams(search),
}));

const TEAMS = [
  { id: "t1", name: "Core", is_member: true },
  { id: "t2", name: "Ops", is_member: false },
  { id: "t3", name: "Sales", is_member: false },
];

function setup(role: string, status = "active", over: Partial<Project> = {}, teams: Promise<unknown> | unknown = []) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/teams") return new Response(JSON.stringify(await teams));
      if (init?.method === "PATCH") return new Response("{}");
      const body =
        url === "/api/projects/PAY" ? { ...project(over), status }
        : url === "/api/auth/me" ? { user: { id: "u1", name: "M", email: "m@x.io", role } }
        : url === "/api/projects/PAY/columns" ? [{ id: "c1", name: "To Do", category: "before", position: 0, task_count: 0 }]
        : url === "/api/projects/PAY/repositories" ? [{ id: "r1", name: "pay", url: "https://g/pay", provider: "github", default_branch: "main", connection: null }]
        : url === "/api/projects/PAY/labels" ? [{ id: "l1", name: "urgent", color: "#ff0000" }]
        : [];
      return new Response(JSON.stringify(body));
    });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ProjectSettingsPage />
    </QueryClientProvider>,
  );
  return fetchMock;
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

  it("read-only teams name the project's teams, or say None", async () => {
    setup("member", "active", { team_ids: ["t1", "t2"] }, TEAMS);
    await screen.findByText("urgent");
    expect(await panel("General").findByText("Core, Ops")).toBeInTheDocument();
    cleanup();
    setup("member", "active", { team_ids: [] }, TEAMS);
    await screen.findByText("urgent");
    expect(await panel("General").findByText("None")).toBeInTheDocument();
  });

  it("read-only teams wait for the team list instead of calling them unseen", async () => {
    setup("member", "active", { team_ids: ["t1"] }, new Promise(() => {}));
    await screen.findByText("urgent");
    expect(panel("General").queryByText("A team you can't see")).toBeNull();
    expect(panel("General").getByText("Loading…")).toBeInTheDocument();
  });

  it("a manager keeps a project's team they don't belong to, ticked, and saving keeps it", async () => {
    const fetchMock = setup("manager", "active", { team_ids: ["t2"] }, TEAMS);
    await screen.findByText("urgent");
    const core = await panel("General").findByRole("checkbox", { name: "Core" });
    expect(core).not.toBeChecked();
    expect(panel("General").getByRole("checkbox", { name: "Ops" })).toBeChecked();
    expect(panel("General").queryByRole("checkbox", { name: "Sales" })).toBeNull();
    fireEvent.click(panel("General").getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, i]) => (i as RequestInit | undefined)?.method === "PATCH")).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([, i]) => (i as RequestInit | undefined)?.method === "PATCH")!;
    expect(JSON.parse((init as RequestInit).body as string).team_ids).toEqual(["t2"]);
  });
});
