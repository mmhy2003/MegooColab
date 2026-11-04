import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/kb/drafts/d1",
  useSearchParams: () => new URLSearchParams(),
}));

import { DiscardDraftButton, SaveDraftDialog } from "@/components/kb/drafts/SaveDraftDialog";

const DRAFT = {
  id: "d1", title: "Runbook", body_md: "x", open_marks: 2, segments: [], messages: [],
  agent: { id: "a1", name: "laptop-claude", online: true, runner_ok: true },
  space: { id: "s1", kind: "project", name: "Payments" }, folder_id: null, folder_path: "",
  document: { id: "doc1", latest_revision: 5 }, base_revision: 3, state: "idle", last_activity_at: "2026-11-04T10:00:00Z",
};

function renderUi(ui: React.ReactNode, { conflict = false } = {}) {
  const calls: { url: string; method: string; body?: unknown }[] = [];
  let saves = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (url.endsWith("/save")) {
      saves += 1;
      if (conflict && saves === 1) return new Response(JSON.stringify({ detail: "kb_conflict" }), { status: 409 });
      return new Response(JSON.stringify({ document_id: "doc1" }), { status: 200 });
    }
    if (url.includes("/diff/")) {
      return new Response(JSON.stringify([{ op: "insert", a_start: 1, b_start: 1, a_lines: [], b_lines: ["Theirs"] }]), { status: 200 });
    }
    if (method === "DELETE") return new Response(null, { status: 204 });
    return new Response(JSON.stringify(DRAFT), { status: 200 });
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  push.mockReset();
});

describe("SaveDraftDialog", () => {
  it("says how many changes are not reviewed, and saves with the summary", async () => {
    const calls = renderUi(<SaveDraftDialog draft={DRAFT as never} open onClose={() => {}} />);
    expect(screen.getByText("2 changes not reviewed")).toBeInTheDocument();
    expect(screen.getByLabelText("Summary of change (optional)")).toHaveAttribute("placeholder", "Written with laptop-claude");
    fireEvent.change(screen.getByLabelText("Summary of change (optional)"), { target: { value: "first cut" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/kb/doc/doc1"));
    expect(calls.find((c) => c.url.endsWith("/save"))?.body).toEqual({ summary: "first cut", force: false });
  });

  it("offers what to do when someone saved a newer version", async () => {
    const calls = renderUi(<SaveDraftDialog draft={DRAFT as never} open onClose={() => {}} />, { conflict: true });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Someone saved a newer version.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show what changed" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/kb/documents/doc1/revisions/3/diff/5")).toBe(true));
    expect(await screen.findByText("Theirs")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ask the agent to bring it in" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/kb/drafts/d1/bring-in")).toBe(true));
  });

  it("saves over the newer version after a confirmation", async () => {
    const calls = renderUi(<SaveDraftDialog draft={DRAFT as never} open onClose={() => {}} />, { conflict: true });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    fireEvent.click(await screen.findByRole("button", { name: "Save over it anyway" }));
    fireEvent.click(await screen.findByRole("button", { name: "Save over it" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/kb/doc/doc1"));
    expect(calls.filter((c) => c.url.endsWith("/save")).map((c) => c.body)).toEqual([
      { summary: null, force: false }, { summary: null, force: true },
    ]);
  });
});

describe("DiscardDraftButton", () => {
  it("asks, then deletes the draft and goes back to the document", async () => {
    const calls = renderUi(<DiscardDraftButton draft={DRAFT as never} />);
    fireEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    expect(await screen.findByText("The draft and its conversation are deleted.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/kb/doc/doc1"));
    expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/kb/drafts/d1")).toBe(true);
  });
});
