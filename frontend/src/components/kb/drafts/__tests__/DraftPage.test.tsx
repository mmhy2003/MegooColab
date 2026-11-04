import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/kb/drafts/d1",
  useSearchParams: () => new URLSearchParams(),
}));

import { DraftPage } from "@/components/kb/drafts/DraftPage";

const AGENT = { id: "a1", name: "laptop-claude", online: true, runner_ok: true };

function draft(over: Record<string, unknown> = {}) {
  return {
    id: "d1", title: "Deploying payments", body_md: "", open_marks: 2,
    segments: [
      { kind: "text", md: "# Deploying payments" },
      { kind: "mark", id: 0, change: "changed", request: "shorten the prerequisites",
        old_md: "## Prerequisites\n\nYou need cluster access", new_md: "## Prerequisites\n\nYou need prod access" },
      { kind: "text", md: "## Smoke checks\n\nBefore starting, run the checkout test." },
      { kind: "mark", id: 1, change: "added", request: "shorten the prerequisites", old_md: "", new_md: "## Rollback" },
    ],
    messages: [
      { id: "m1", author: "person", text: "A runbook", target: null, created_at: "2026-11-04T10:00:00Z" },
      { id: "m2", author: "agent", text: "Drafted 4 sections.", target: null, created_at: "2026-11-04T10:01:00Z" },
    ],
    agent: AGENT, space: { id: "s1", kind: "project", name: "Payments" }, folder_id: null, folder_path: "",
    document: null, base_revision: null, state: "idle", last_activity_at: "2026-11-04T10:01:00Z",
    ...over,
  };
}

function renderPage(first: Record<string, unknown>) {
  const calls: { url: string; method: string; body?: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (url.includes("/agents")) return new Response(JSON.stringify([AGENT]), { status: 200 });
    if (url.includes("/resolve")) return new Response(JSON.stringify({}), { status: 200 });
    if (url.endsWith("/settle")) return new Response(JSON.stringify(draft({ open_marks: 0, segments: [{ kind: "text", md: "# All" }], body_md: "# All" })), { status: 200 });
    return new Response(JSON.stringify(method === "GET" ? first : draft({ open_marks: 0 })), { status: 200 });
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DraftPage draftId="d1" />
    </QueryClientProvider>,
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  push.mockReset();
});

describe("DraftPage", () => {
  it("shows a changed block word by word, with the request it came from", async () => {
    renderPage(draft());
    expect(await screen.findByText("Draft · not saved")).toBeInTheDocument();
    const struck = screen.getAllByText((_, el) => el?.tagName === "DEL" && el.textContent === "cluster");
    const added = screen.getAllByText((_, el) => el?.tagName === "INS" && el.textContent === "prod");
    expect(struck.length).toBe(1);
    expect(added.length).toBe(1);
    expect(screen.getAllByText(/shorten the prerequisites/).length).toBeGreaterThan(0);
  });

  it("keeps or undoes one change, or all of them", async () => {
    const calls = renderPage(draft());
    await screen.findByText("Draft · not saved");
    fireEvent.click(screen.getAllByRole("button", { name: "Undo" })[0]);
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/kb/drafts/d1/marks/0/undo")).toBe(true));
    expect(screen.getByRole("button", { name: "Keep all" })).toBeInTheDocument();
  });

  it("has no Keep all without open changes", async () => {
    renderPage(draft({ open_marks: 0, segments: [{ kind: "text", md: "# Done" }] }));
    await screen.findByText("Draft · not saved");
    expect(screen.queryByRole("button", { name: "Keep all" })).not.toBeInTheDocument();
  });

  it("is read-only while the agent writes, and Stop stops it", async () => {
    const calls = renderPage(draft({ state: "writing" }));
    expect((await screen.findAllByText(/laptop-claude is writing…/)).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Edit text" })).toBeDisabled();
    fireEvent.click(screen.getAllByRole("button", { name: "Stop" })[0]);
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/kb/drafts/d1/stop")).toBe(true));
  });

  it("aims the next request at the selected text", async () => {
    const calls = renderPage(draft());
    const para = await screen.findByText(/Before starting, run the checkout test/);
    vi.spyOn(window, "getSelection").mockReturnValue({
      toString: () => "Before starting", anchorNode: para.firstChild,
    } as unknown as Selection);
    fireEvent.mouseUp(para);
    expect(screen.getByText("About: selected text in 'Smoke checks'")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Your request"), { target: { value: "make it a checklist" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(calls.find((c) => c.url.endsWith("/requests"))?.body).toEqual({
      text: "make it a checklist", target: { section: "Smoke checks", text: "Before starting" },
    }));
  });

  it("keeps the open changes before the editor opens", async () => {
    const calls = renderPage(draft());
    expect(await screen.findByText("Keeps the 2 open changes")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit text" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/kb/drafts/d1/settle")).toBe(true));
    expect(await screen.findByLabelText("Body")).toHaveValue("# All");
    fireEvent.change(screen.getByLabelText("Body"), { target: { value: "# All\n\nmine" } });
    fireEvent.click(screen.getByRole("button", { name: "Done editing" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ body_md: "# All\n\nmine" }));
  });
});
