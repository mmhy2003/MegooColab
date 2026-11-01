import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useParams: () => ({ docId: "d2", spaceId: "s1" }),
  usePathname: () => "/kb/doc/d2",
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(search),
}));

import KbSpacePage from "@/app/(app)/kb/[spaceId]/page";
import KbDocumentPage from "@/app/(app)/kb/doc/[docId]/page";
import KbSearchPage from "@/app/(app)/kb/search/page";
import { recordVisit } from "@/lib/backNav";
import { backNameOf, useShownTrail } from "@/lib/trail";

const SPACE = { id: "s1", kind: "team", name: "Core", can_write: true };
const doc = (id: string, title: string) => ({ id, folder_id: "f1", title, latest_revision: 1, updated_at: "2026-10-20T10:00:00Z" });
const TREE = {
  folders: [{ id: "f1", parent_id: null, name: "Guides" }],
  documents: [doc("d1", "Alpha"), doc("d2", "Beta"), doc("d3", "Gamma")],
};
const DOC = {
  id: "d2",
  space: { id: "s1", kind: "team", name: "Core" },
  folder_id: "f1",
  path: "Guides",
  title: "Beta",
  body_md: "Beta body",
  latest_revision: 2,
  created_by: "u1",
  updated_at: "2026-10-26T10:00:00Z",
  updated_by: { user: { id: "u1", name: "Ann" }, agent: null },
  can_write: true,
  can_delete: true,
};

function Probe() {
  const trail = useShownTrail("/kb/doc/d2");
  return (
    <p data-testid="trail" data-back={backNameOf(trail) ?? ""}>
      {trail.crumbs.map((c) => c.label ?? "…").join(" › ")}
    </p>
  );
}

function show(ui: React.ReactNode) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body =
        url.startsWith("/api/kb/search") ? { semantic: false, results: [] } : url === "/api/kb/spaces" ? [SPACE] : url === "/api/kb/spaces/s1/tree" ? TREE : url === "/api/kb/documents/d2" ? DOC : [];
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      {ui}
      <Probe />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  search = "";
  push.mockClear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the Knowledge Base reader", () => {
  it("a document shows the tree, its trail, the pager and Back to its folder when opened directly", async () => {
    show(<KbDocumentPage />);
    const files = await screen.findByRole("complementary", { name: "Files" });
    const current = await within(files).findByRole("link", { name: "Beta" });
    expect(current).toHaveAttribute("aria-current", "page");
    expect(within(files).getByRole("link", { name: "Gamma" })).toHaveAttribute("href", "/kb/doc/d3");
    await waitFor(() => expect(screen.getByTestId("trail")).toHaveTextContent("Knowledge Base › Core › Guides › Beta"));
    const pager = screen.getByRole("navigation", { name: "Folder" });
    expect(within(pager).getByRole("link", { name: "← Alpha" })).toHaveAttribute("href", "/kb/doc/d1");
    expect(within(pager).getByRole("link", { name: "Gamma →" })).toHaveAttribute("href", "/kb/doc/d3");
    expect(screen.getByRole("link", { name: "← Back to Guides" })).toHaveAttribute("href", "/kb/s1?folder=f1");
  });

  it("the search box searches this space", async () => {
    show(<KbDocumentPage />);
    const box = await screen.findByRole("searchbox", { name: "Search the Knowledge Base" });
    expect(box).toHaveAttribute("placeholder", "Search the Knowledge Base…");
    fireEvent.change(box, { target: { value: "retry policy" } });
    fireEvent.submit(box);
    expect(push).toHaveBeenCalledWith("/kb/search?q=retry+policy&space=s1");
  });

  it("the tree folds away while editing", async () => {
    search = "edit=1";
    show(<KbDocumentPage />);
    await screen.findByLabelText("Body");
    expect(screen.queryByRole("complementary", { name: "Files" })).toBeNull();
  });

  it("a folder: picking another folder adds a history step, and Back leads up to the space", async () => {
    search = "folder=f1";
    show(<KbSpacePage />);
    const files = await screen.findByRole("complementary", { name: "Files" });
    expect(await screen.findByRole("link", { name: "← Back to Core" })).toHaveAttribute("href", "/kb/s1");
    fireEvent.click(within(files).getByRole("button", { name: "All documents" }));
    expect(push).toHaveBeenCalledWith("/kb/s1");
  });

  it("search results: their trail, their name for Back, and Back to where the search started", async () => {
    search = "q=retry";
    recordVisit("/projects/PAY/board", "Board");
    recordVisit("/kb/search?q=retry", null);
    show(<KbSearchPage />);
    await waitFor(() => expect(screen.getByTestId("trail")).toHaveTextContent("Knowledge Base › Search"));
    expect(screen.getByTestId("trail")).toHaveAttribute("data-back", 'results for "retry"');
    expect(await screen.findByRole("link", { name: "← Back to Board" })).toHaveAttribute("href", "/projects/PAY/board");
    expect(screen.queryByText("Knowledge Base", { selector: "p a" })).toBeNull();
  });
});
