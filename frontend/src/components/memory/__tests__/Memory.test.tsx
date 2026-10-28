import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AskMemory } from "@/components/memory/AskMemory";
import { ConclusionItem } from "@/components/memory/ConclusionItem";
import { EntityList } from "@/components/memory/EntityList";
import { ReasoningChain } from "@/components/memory/ReasoningChain";
import type { MemChainNode, MemConclusion, MemEntity } from "@/lib/memory";
import { answer } from "@/test/answer";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function conclusion(over: Partial<MemConclusion> = {}): MemConclusion {
  return {
    id: "c1",
    entity_id: "e1",
    entity_name: "PAY — Payments",
    text: "Webhooks are signed with **HMAC**",
    kind: "observed",
    confidence: null,
    status: "active",
    pinned: false,
    scope: { kind: "project", id: "p1", name: "PAY — Payments" },
    source: { kind: "comment", label: "Comment on PAY-1", link: "/projects/PAY/tasks/1" },
    created_at: "2026-10-26T10:00:00Z",
    can_edit: true,
    ...over,
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AskMemory", () => {
  it("shows answer with numbered citations and errors", async () => {
    let fail = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === "/api/projects") return json([{ id: "p1", key: "PAY", name: "Payments" }]);
        if (url === "/api/memory/ask") {
          return fail
            ? json({ detail: "memory_answering_not_configured" }, 409)
            : json({ answer_md: "Signed with **HMAC**.", cited: [conclusion()] });
        }
        return json([]);
      }),
    );
    wrap(<AskMemory />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "How are webhooks signed?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("HMAC", { selector: "strong" })).toBeInTheDocument();
    const cites = screen.getByRole("list", { name: "Sources" });
    expect(within(cites).getByText("[1]")).toBeInTheDocument();
    expect(within(cites).getByRole("link", { name: /PAY — Payments/ })).toHaveAttribute("href", "/memory/entity/e1");
    fail = true;
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No AI model is set up for answering");
  });

  it("sends project_key when chosen", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/projects") return json([{ id: "p1", key: "PAY", name: "Payments" }]);
      return json({ answer_md: "x", cited: [] });
    });
    vi.stubGlobal("fetch", fetchMock);
    wrap(<AskMemory />);
    await screen.findByRole("option", { name: "PAY — Payments" });
    fireEvent.change(screen.getByLabelText("Project (optional)"), { target: { value: "PAY" } });
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "q?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => u === "/api/memory/ask")).toBe(true));
    const call = fetchMock.mock.calls.find(([u]) => u === "/api/memory/ask")! as unknown as [string, RequestInit];
    expect(JSON.parse(call[1].body as string)).toEqual({ question: "q?", project_key: "PAY" });
  });
});

describe("ConclusionItem", () => {
  it("hides actions without can_edit", () => {
    wrap(<ConclusionItem conclusion={conclusion({ can_edit: false })} />);
    expect(screen.queryByRole("button", { name: "Correct" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pin" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Why?" })).toBeInTheDocument();
  });

  it("correct sends text and delete asks first", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === "DELETE" ? new Response(null, { status: 204 }) : json(conclusion({ id: "c2", kind: "correction" })),
    );
    vi.stubGlobal("fetch", fetchMock);
    wrap(<ConclusionItem conclusion={conclusion()} />);
    fireEvent.click(screen.getByRole("button", { name: "Correct" }));
    fireEvent.change(screen.getByLabelText("Corrected text"), { target: { value: "Signed with HMAC SHA256" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/memory/conclusions/c1/correct");
    expect(JSON.parse(init.body as string)).toEqual({ text: "Signed with HMAC SHA256" });

    fetchMock.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("alertdialog")).toHaveAccessibleDescription(/not be learned again/);
    await answer("Cancel");
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await answer("Delete");
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].method).toBe("DELETE");
  });

  it("renders induced confidence and source link or deleted note", () => {
    const { unmount } = wrap(<ConclusionItem conclusion={conclusion({ kind: "induced", confidence: 0.6 })} />);
    expect(screen.getByText("induced · 60%")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Comment on PAY-1" })).toHaveAttribute("href", "/projects/PAY/tasks/1");
    unmount();
    wrap(<ConclusionItem conclusion={conclusion({ source: { kind: "comment", label: "Gone", link: null } })} />);
    expect(screen.getByText("(source deleted)")).toBeInTheDocument();
  });

  it("conclusion text renders as markdown without raw html", () => {
    const { container } = wrap(
      <ConclusionItem conclusion={conclusion({ text: 'Bad <img src=x onerror="alert(1)"> **bold**' })} />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("bold", { selector: "strong" })).toBeInTheDocument();
  });
});

describe("ReasoningChain", () => {
  it("renders nested premises", () => {
    const nodes: MemChainNode[] = [
      {
        conclusion: conclusion({ id: "p1", text: "First premise", kind: "deduced" }),
        premises: [{ conclusion: conclusion({ id: "p2", text: "Deeper premise" }), premises: [] }],
      },
    ];
    render(<ReasoningChain nodes={nodes} />);
    const outer = screen.getByText("First premise").closest("li")!;
    expect(within(outer).getByText("Deeper premise")).toBeInTheDocument();
    expect(within(outer).getAllByText("deduced")).toHaveLength(1);
  });

  it("says when there is no chain", () => {
    render(<ReasoningChain nodes={[]} />);
    expect(screen.getByText("Learned directly from its source.")).toBeInTheDocument();
  });
});

describe("EntityList", () => {
  const ents: MemEntity[] = [
    { id: "o", kind: "org", name: "Organization", description: "", conclusion_count: 3 },
    { id: "p", kind: "project", name: "PAY — Payments", description: "", conclusion_count: 5 },
    { id: "u", kind: "user", name: "Mia", description: "", conclusion_count: 0 },
    { id: "x", kind: "product", name: "Atlas", description: "", conclusion_count: 1 },
  ];

  it("groups by kind and filters", () => {
    render(<EntityList entities={ents} />);
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(["Organization", "Projects", "Products", "People"]);
    expect(screen.getByRole("link", { name: /PAY — Payments/ })).toHaveAttribute("href", "/memory/entity/p");
    expect(screen.getByText("5 conclusions")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter entities"), { target: { value: "atl" } });
    expect(screen.queryByRole("link", { name: /PAY/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Atlas/ })).toBeInTheDocument();
  });
});
