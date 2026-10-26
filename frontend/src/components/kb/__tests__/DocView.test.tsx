import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: push }) }));

import { Backlinks } from "@/components/kb/Backlinks";
import { DiffView } from "@/components/kb/DiffView";
import { DocEditor } from "@/components/kb/DocEditor";
import { DocView } from "@/components/kb/DocView";
import { Markdown } from "@/components/ui/Markdown";
import type { DiffOp, KbDocument } from "@/lib/kb";

const DOC: KbDocument = {
  id: "d1",
  space: { id: "s1", kind: "team", name: "Core" },
  folder_id: null,
  path: "guides",
  title: "Webhooks",
  body_md: "Body v2",
  latest_revision: 2,
  created_by: "u1",
  updated_at: "2026-10-26T10:00:00Z",
  updated_by: { user: { id: "u1", name: "Ann" }, agent: { id: "a1", name: "Builder" } },
  can_write: true,
  can_delete: true,
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  push.mockReset();
});

describe("DocEditor", () => {
  it("sends base_revision", async () => {
    const fetchMock = vi.fn(async () => json({ ...DOC, latest_revision: 3 }));
    vi.stubGlobal("fetch", fetchMock);
    const onSaved = vi.fn();
    wrap(<DocEditor doc={DOC} onSaved={onSaved} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Body"), { target: { value: "Body v3" } });
    fireEvent.change(screen.getByLabelText("Summary of change (optional)"), { target: { value: "typo" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/kb/documents/d1");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ base_revision: 2, title: "Webhooks", body_md: "Body v3", summary: "typo" });
  });

  it("conflict keeps draft and Load latest asks", async () => {
    let latest = false;
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT") return json({ detail: "kb_conflict" }, 409);
      if (url === "/api/kb/documents/d1") {
        latest = true;
        return json({ ...DOC, body_md: "Theirs", latest_revision: 3 });
      }
      return json([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const answers = [false, true];
    const confirmMock = vi.fn(() => answers.shift()!);
    vi.stubGlobal("confirm", confirmMock);
    wrap(<DocEditor doc={DOC} onSaved={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Body"), { target: { value: "Mine" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Someone saved a newer version");
    expect(screen.getByLabelText("Body")).toHaveValue("Mine");

    fireEvent.click(screen.getByRole("button", { name: "Load latest" }));
    expect(confirmMock).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Body")).toHaveValue("Mine"); // declined: draft kept
    fireEvent.click(screen.getByRole("button", { name: "Load latest" }));
    await waitFor(() => expect(screen.getByLabelText("Body")).toHaveValue("Theirs"));
    expect(latest).toBe(true);

    // the next save is based on the revision just loaded
    fetchMock.mockImplementation(async () => json({ ...DOC, latest_revision: 4 }));
    fireEvent.change(screen.getByLabelText("Body"), { target: { value: "Merged" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, i]) => (i as RequestInit | undefined)?.method === "PUT")).toBe(true));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([, i]) => (i as RequestInit | undefined)?.method === "PUT")).toHaveLength(2));
    const put = fetchMock.mock.calls.filter(([, i]) => (i as RequestInit | undefined)?.method === "PUT").at(-1)!;
    expect(JSON.parse((put[1] as RequestInit).body as string).base_revision).toBe(3);
  });

  it("shows a preview of the draft", () => {
    wrap(<DocEditor doc={DOC} onSaved={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Body"), { target: { value: "# Heading here" } });
    expect(screen.getByRole("heading", { name: "Heading here" })).toBeInTheDocument();
  });
});

describe("DiffView", () => {
  it("marks insert/delete with text, not colour only", () => {
    const ops: DiffOp[] = [
      { op: "collapsed", count: 7 },
      { op: "equal", a_start: 8, b_start: 8, a_lines: ["same"], b_lines: ["same"] },
      { op: "replace", a_start: 9, b_start: 9, a_lines: ["old"], b_lines: ["new"] },
      { op: "insert", a_start: 10, b_start: 10, a_lines: [], b_lines: ["added"] },
      { op: "delete", a_start: 10, b_start: 11, a_lines: ["gone"], b_lines: [] },
    ];
    render(<DiffView ops={ops} />);
    expect(screen.getByText("7 unchanged lines")).toBeInTheDocument();
    const added = screen.getByText("added").closest("[data-op]")!;
    expect(added).toHaveTextContent("+");
    expect(added).toHaveAttribute("aria-label", "Added line 10");
    const removed = screen.getByText("gone").closest("[data-op]")!;
    expect(removed).toHaveTextContent("−");
    expect(removed).toHaveAttribute("aria-label", "Removed line 10");
    expect(screen.getByText("old").closest("[data-op]")).toHaveTextContent("−");
    expect(screen.getByText("new").closest("[data-op]")).toHaveTextContent("+");
  });
});

describe("Markdown wiki links", () => {
  const titles = {
    "11111111-1111-1111-1111-111111111111": { title: "Setup guide", readable: true },
    "22222222-2222-2222-2222-222222222222": { title: null, readable: false },
  };

  it("renders task and doc wiki links and restricted placeholder", () => {
    render(
      <Markdown wiki={titles}>
        {"See [[PAY-12]], [[doc:11111111-1111-1111-1111-111111111111]], " +
          "[[doc:11111111-1111-1111-1111-111111111111|the guide]] and [[doc:22222222-2222-2222-2222-222222222222|Secret]]. " +
          "Literal: [[not a link]] and `[[PAY-1]]`."}
      </Markdown>,
    );
    expect(screen.getByRole("link", { name: "PAY-12" })).toHaveAttribute("href", "/projects/PAY/tasks/12");
    expect(screen.getByRole("link", { name: "Setup guide" })).toHaveAttribute("href", "/kb/doc/11111111-1111-1111-1111-111111111111");
    expect(screen.getByRole("link", { name: "the guide" })).toBeInTheDocument();
    expect(screen.getByText(/\(restricted document\)/)).toBeInTheDocument();
    expect(screen.queryByText(/Secret/)).not.toBeInTheDocument();
    expect(screen.getByText(/\[\[not a link\]\]/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "PAY-1" })).not.toBeInTheDocument(); // code stays code
  });

  it("wiki link cannot produce javascript href", () => {
    const { container } = render(
      <Markdown wiki={{}}>{"[[doc:javascript:alert(1)]] [[javascript:alert(1)]] [x](javascript:alert(1)) [[doc:javascript:x|y]]"}</Markdown>,
    );
    for (const a of Array.from(container.querySelectorAll("a"))) {
      expect(a.getAttribute("href") ?? "").not.toMatch(/javascript:/i);
    }
  });

  it("leaves wiki syntax alone without the wiki prop", () => {
    render(<Markdown>{"[[PAY-12]]"}</Markdown>);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});

describe("Backlinks", () => {
  it("lists documents that link here", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json([{ id: "d9", title: "Overview", space: { id: "s2", kind: "org", name: "Organization" } }])));
    wrap(<Backlinks docId="d1" />);
    expect(await screen.findByRole("link", { name: "Overview" })).toHaveAttribute("href", "/kb/doc/d9");
    expect(screen.getByText("Organization")).toBeInTheDocument();
  });

  it("says when nothing links here", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json([])));
    wrap(<Backlinks docId="d1" />);
    expect(await screen.findByText("No other documents link here.")).toBeInTheDocument();
  });
});

describe("DocView", () => {
  it("shows author with agent and the path", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({})));
    wrap(<DocView doc={DOC} onEdit={vi.fn()} />);
    expect(screen.getByText("guides/Webhooks")).toBeInTheDocument();
    expect(screen.getByText(/Ann \(via Builder\)/)).toBeInTheDocument();
    expect(screen.getByText("rev 2")).toBeInTheDocument();
  });

  it("delete asks then navigates to space", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === "DELETE" ? new Response(null, { status: 204 }) : json([]),
    );
    vi.stubGlobal("fetch", fetchMock);
    const answers = [false, true];
    vi.stubGlobal("confirm", () => answers.shift()!);
    wrap(<DocView doc={DOC} onEdit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(fetchMock.mock.calls.some(([, i]) => i?.method === "DELETE")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/kb/s1"));
    expect(fetchMock.mock.calls.find(([, i]) => i?.method === "DELETE")![0]).toBe("/api/kb/documents/d1");
  });

  it("hides actions the viewer may not take", () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({})));
    wrap(<DocView doc={{ ...DOC, can_write: false, can_delete: false }} onEdit={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Move" })).not.toBeInTheDocument();
  });
});
