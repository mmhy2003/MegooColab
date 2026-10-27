import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SearchAdmin } from "@/components/admin/SearchAdmin";
import { SearchResults } from "@/components/search/SearchResults";
import { paramsFromUrl, type SearchParams } from "@/lib/search";

const hit = (n: number, extra: Record<string, unknown> = {}) => ({
  kind: "task", id: `t${n}`, title: `Retry payments ${n}`, key: `PAY-${n}`, url: `/projects/PAY/board?task=PAY-${n}`,
  snippet: "", project_key: "PAY", status: "done", updated_at: 1_790_000_000 - n, card: null, ...extra,
});

const FACETS = {
  kind: { task: 21, document: 9 },
  project: [{ id: "11111111-1111-1111-1111-111111111111", key: "PAY", count: 30 }],
  status: { before: 4, done: 17 },
  assignee: [{ id: "user:22222222-2222-2222-2222-222222222222", name: "Ann Lee", count: 3 }],
  type: { task: 18, bug: 3 },
  label: { ops: 2 },
};

function page(hits: unknown[], extra: Record<string, unknown> = {}) {
  return { hits, total: 25, facets: FACETS, meaning: null, meaning_available: false, ...extra };
}

type Handler = (url: string, init?: RequestInit) => unknown;

function setup(handler: Handler, initial = "q=payments") {
  const calls: string[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(url);
    const body = handler(url, init);
    if (body instanceof Response) return body;
    return new Response(JSON.stringify(body ?? {}), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const urls: string[] = [];
  function Harness() {
    const [params, setParams] = useState<SearchParams>(paramsFromUrl(new URLSearchParams(initial)));
    return (
      <SearchResults
        params={params}
        onChange={(p, url) => {
          urls.push(url);
          setParams(p);
        }}
      />
    );
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
  return { calls, urls, fetchMock };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SearchResults", () => {
  it("shows facet counts and puts filters in the URL", async () => {
    const { calls, urls } = setup(() => page([hit(1)]));
    const tasks = await screen.findByRole("checkbox", { name: "Tasks (21)" });
    expect(screen.getByRole("checkbox", { name: "Documents (9)" })).toBeInTheDocument();
    fireEvent.click(tasks);
    fireEvent.click(screen.getByRole("checkbox", { name: "Done (17)" }));
    await waitFor(() => expect(calls.at(-1)).toBe("/api/search?q=payments&kind=task&status=done"));
    expect(urls.at(-1)).toBe("q=payments&kind=task&status=done");
    expect(screen.getByRole("checkbox", { name: "PAY (30)" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Ann Lee (3)" })).toBeInTheDocument();
  });

  it("says when filters narrow the results to tasks", async () => {
    setup(() => page([hit(1)]), "q=payments&status=done");
    expect(await screen.findByText("Showing tasks only (status applies to tasks)")).toBeInTheDocument();
  });

  it("sorts and loads more", async () => {
    const { calls } = setup((url) =>
      url.includes("offset=20") ? page([hit(21), hit(22)]) : page(Array.from({ length: 20 }, (_, i) => hit(i + 1))),
    );
    expect(await screen.findAllByRole("article")).toHaveLength(20);
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(22));
    expect(calls).toContain("/api/search?q=payments&offset=20");
    fireEvent.change(screen.getByLabelText("Sort"), { target: { value: "newest" } });
    await waitFor(() => expect(calls.at(-1)).toBe("/api/search?q=payments&sort=newest"));
  });

  it("offers the meaning switch only when it can be used", async () => {
    const off = setup(() => page([hit(1)]));
    await screen.findAllByRole("article");
    expect(screen.queryByRole("checkbox", { name: "Also match by meaning" })).toBeNull();
    cleanup();
    vi.unstubAllGlobals();
    const on = setup((url) =>
      page([hit(1)], {
        meaning_available: true,
        meaning: url.includes("meaning=true")
          ? [{ ...hit(9), kind: "document", key: "", title: "Invoicing", url: "/kb/doc/d9", project_key: null }]
          : null,
      }),
    );
    fireEvent.click(await screen.findByRole("checkbox", { name: "Also match by meaning" }));
    const block = await screen.findByRole("region", { name: "Similar in meaning" });
    expect(within(block).getByRole("link", { name: /Invoicing/ })).toHaveAttribute("href", "/kb/doc/d9");
    expect(on.calls.at(-1)).toBe("/api/search?q=payments&meaning=true");
    expect(off.calls.every((c) => !c.includes("meaning"))).toBe(true);
  });

  it("renders results as text, never as HTML", async () => {
    setup(() => page([hit(1, { title: '<img src=x onerror="alert(1)"> Retry', snippet: "<b>bold</b>" })]));
    const article = await screen.findByRole("article");
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
    expect(within(article).getByText("Retry").tagName).toBe("MARK");
    expect(article.textContent).toContain("<b>bold</b>");
  });

  it("says when search is unavailable", async () => {
    setup(() => new Response(JSON.stringify({ detail: "search_unavailable" }), { status: 503 }));
    expect(await screen.findByText("Search is unavailable right now")).toBeInTheDocument();
  });
});

describe("SearchAdmin", () => {
  it("shows the index status and rebuilds after confirmation", async () => {
    const posts: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posts.push(url);
        return new Response(JSON.stringify({ queued: true }), { status: 202 });
      }
      return new Response(JSON.stringify({ available: true, documents: 1234, last_rebuild_at: "2026-10-28T09:00:00Z" }), { status: 200 });
    }));
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <SearchAdmin />
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/1,234 items indexed/)).toBeInTheDocument();
    expect(screen.getByText("Available")).toBeInTheDocument();
    const rebuild = screen.getByRole("button", { name: "Rebuild index" });
    fireEvent.click(rebuild);
    expect(posts).toEqual([]);
    fireEvent.click(rebuild);
    await waitFor(() => expect(posts).toEqual(["/api/admin/search/rebuild"]));
    expect(await screen.findByText("Rebuild queued. It runs in the background.")).toBeInTheDocument();
    confirm.mockRestore();
  });
});
