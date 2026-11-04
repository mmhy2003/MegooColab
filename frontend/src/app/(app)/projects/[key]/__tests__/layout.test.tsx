import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ key: "AUD" }),
  usePathname: () => "/projects/AUD/board",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

import ProjectLayout from "@/app/(app)/projects/[key]/layout";

const NAME = "Audit project with a long descriptive name";

function show(sprints = true) {
  const project = { id: "p1", key: "AUD", name: NAME, description: "", sprints_enabled: sprints, status: "active", team_ids: [] };
  const waiting = [{ id: "q1" }, { id: "q2" }];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = url.includes("/api/questions") ? waiting : url.includes("/api/auth/me") ? { user: { id: "u1", role: "member" } } : project;
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProjectLayout>
        <p>content</p>
      </ProjectLayout>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("project layout", () => {
  it("on phones Questions is the tab bar's last link, with its count", async () => {
    show();
    const nav = await screen.findByRole("navigation", { name: "Project" });
    const links = within(nav).getAllByRole("link");
    const last = links[links.length - 1];
    expect(last).toHaveTextContent("Questions");
    expect(last).toHaveClass("md:hidden");
    expect(last).toHaveAttribute("href", "/questions?tab=incoming&project=AUD");
    expect(await within(last).findByLabelText("2 need an answer")).toBeInTheDocument();
    expect(last).not.toHaveAttribute("aria-current");
  });

  it("Questions is last with sprints off too", async () => {
    show(false);
    const nav = await screen.findByRole("navigation", { name: "Project" });
    expect(within(nav).getAllByRole("link").map((l) => l.textContent?.replace(/\d+$/, ""))).toEqual(["Board", "Chats", "Crons", "Settings", "Questions"]);
  });

  it("from md up the Incoming questions link stays where it is", async () => {
    show();
    const link = await screen.findByRole("link", { name: /Incoming questions/ });
    expect(link).toHaveClass("max-md:hidden");
    expect(screen.getByRole("navigation", { name: "Project" })).not.toContainElement(link);
  });

  it("the project name stays on one line on phones", async () => {
    show();
    const h1 = await screen.findByRole("heading", { level: 1 });
    expect(h1).toHaveClass("max-md:truncate");
    expect(h1).toHaveAttribute("title", `AUD ${NAME}`);
  });

  it("the tab bar is a ScrollX", async () => {
    show();
    expect(await screen.findByRole("navigation", { name: "Project" })).toHaveAttribute("data-scroll-x");
  });
});
