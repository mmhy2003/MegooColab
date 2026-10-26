import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { KbReferences } from "@/components/kb/KbReferences";
import { SearchResults } from "@/components/kb/SearchResults";
import { DocumentView } from "@/components/workflow/DocumentView";
import type { KbSearchHit } from "@/lib/kb";
import { invalidationsFor } from "@/lib/realtime";

const HIT: KbSearchHit = {
  document_id: "d1",
  space: { id: "s1", kind: "org", name: "Organization" },
  title: "Webhooks",
  path: "guides",
  snippet: "Rotate <b>webhook</b> secrets <script>alert(1)</script> every 90 days. Webhook!",
  score: 0.0327,
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SearchResults", () => {
  it("highlights terms without HTML injection", () => {
    const { container } = render(<SearchResults query="webhook (secrets" results={{ semantic: true, results: [HIT] }} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    const marks = Array.from(container.querySelectorAll("mark")).map((m) => m.textContent);
    expect(marks).toEqual(["webhook", "secrets", "Webhook"]);
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Webhooks" })).toHaveAttribute("href", "/kb/doc/d1");
    expect(screen.getByText("guides")).toBeInTheDocument();
    expect(screen.getByText("Organization")).toBeInTheDocument();
  });

  it("semantic-off notice", () => {
    render(<SearchResults query="x" results={{ semantic: false, results: [] }} />);
    expect(screen.getByText(/Semantic search is off/)).toBeInTheDocument();
    expect(screen.getByText("No documents match.")).toBeInTheDocument();
  });
});

describe("KbReferences", () => {
  it("task view shows references", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json([{ id: "d1", title: "Runbook", space: { id: "s1", kind: "team", name: "Core" } }])));
    wrap(<KbReferences taskKey="PAY-1" />);
    expect(await screen.findByRole("heading", { name: "Referenced in Knowledge Base" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Runbook" })).toHaveAttribute("href", "/kb/doc/d1");
  });

  it("renders nothing without references", async () => {
    const fetchMock = vi.fn(async () => json([]));
    vi.stubGlobal("fetch", fetchMock);
    const { container } = wrap(<KbReferences taskKey="PAY-1" />);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

describe("DocumentView", () => {
  it("shows View in Knowledge Base link when filed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/workflow")) {
          return json({ can_act: false, steps: [], documents: [], kb_documents: [{ kind: "design", document_id: "kd1" }] });
        }
        if (url.endsWith("/mockups")) return json([]);
        if (url.endsWith("/documents/design/1")) {
          return json({ kind: "design", version: 1, status: "approved", body_md: "# D", steps: null, attached_mockup_ids: [] });
        }
        return json([{ kind: "design", version: 1, status: "approved", created_at: "2026-10-26T10:00:00Z" }]);
      }),
    );
    wrap(<DocumentView taskKey="PAY-1" kind="design" />);
    expect(await screen.findByRole("link", { name: "View in Knowledge Base" })).toHaveAttribute("href", "/kb/doc/kd1");
  });
});

describe("realtime", () => {
  it("task events refresh Knowledge Base references", () => {
    expect(invalidationsFor({ type: "task.deleted", project_id: "p1" }, new Map())).toContainEqual(["kb", "refs"]);
  });
});
