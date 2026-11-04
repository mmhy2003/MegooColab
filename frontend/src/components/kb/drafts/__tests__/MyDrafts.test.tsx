import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DraftBanner } from "@/components/kb/drafts/DraftBanner";
import { MyDrafts } from "@/components/kb/drafts/MyDrafts";

const DRAFTS = [
  { id: "d1", title: "", space: { id: "s1", kind: "project", name: "Payments" }, document_id: null,
    agent: { id: "a1", name: "laptop-claude" }, last_activity_at: "2026-11-04T10:00:00Z" },
  { id: "d2", title: "Runbook", space: { id: "s1", kind: "project", name: "Payments" }, document_id: "doc1",
    agent: { id: "a1", name: "laptop-claude" }, last_activity_at: "2026-11-04T09:00:00Z" },
];

function renderWith(ui: React.ReactNode, drafts: unknown[] = DRAFTS) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(drafts), { status: 200 })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("MyDrafts", () => {
  it("links each draft to its writing page", async () => {
    renderWith(<MyDrafts />);
    expect(await screen.findByRole("link", { name: /Untitled draft/ })).toHaveAttribute("href", "/kb/drafts/d1");
    expect(screen.getByRole("link", { name: /Runbook/ })).toHaveAttribute("href", "/kb/drafts/d2");
    expect(screen.getByRole("heading", { name: "My drafts" })).toBeInTheDocument();
  });

  it("shows nothing without drafts", async () => {
    const { container } = renderWith(<MyDrafts />, []);
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
  });
});

describe("DraftBanner", () => {
  it("tells the person about their unsaved draft of the document", async () => {
    renderWith(<DraftBanner documentId="doc1" />);
    expect(await screen.findByText(/You have an unsaved draft with laptop-claude/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute("href", "/kb/drafts/d2");
  });

  it("shows nothing for a document without a draft", async () => {
    const { container } = renderWith(<DraftBanner documentId="other" />);
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
  });
});
