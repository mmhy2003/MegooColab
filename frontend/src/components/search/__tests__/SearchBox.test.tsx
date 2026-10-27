import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

import { SearchLauncher } from "@/components/search/SearchBox";

const hit = (kind: string, id: string, title: string, extra: Record<string, unknown> = {}) => ({
  kind, id, title, key: "", url: null, snippet: "", project_key: null, status: null, updated_at: 0, card: null, ...extra,
});

const GROUPS = {
  groups: [
    { kind: "task", hits: [hit("task", "t1", "Retry failed payments", { key: "PAY-42", url: "/projects/PAY/board?task=PAY-42" }),
                           hit("task", "t2", "Payment report", { key: "PAY-7", url: "/projects/PAY/board?task=PAY-7" })] },
    { kind: "document", hits: [hit("document", "d1", "Retry policy", { url: "/kb/doc/d1" })] },
    { kind: "person", hits: [hit("person", "u1", "Ann Lee", { card: { email: "ann@acme.io", teams: [{ id: "tm1", name: "Payments" }] } })] },
    { kind: "agent", hits: [hit("agent", "a1", "Ann's Codex", { card: { owner_name: "Ann Lee", projects: [{ id: "p1", key: "PAY" }] } })] },
  ],
  total: 37,
};

function setup(response: () => Response = () => new Response(JSON.stringify(GROUPS), { status: 200 })) {
  const fetchMock = vi.fn<(url: string) => Promise<Response>>(async () => response());
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SearchLauncher />
    </QueryClientProvider>,
  );
  return fetchMock;
}

function open() {
  fireEvent.keyDown(window, { key: "k", ctrlKey: true });
  return screen.getByRole("combobox", { name: "Search" });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  push.mockReset();
});

describe("SearchLauncher", () => {
  it("opens with Ctrl+K, Cmd+K or the header button, and Esc closes", () => {
    setup();
    open();
    fireEvent.keyDown(screen.getByRole("combobox", { name: "Search" }), { key: "Escape" });
    expect(screen.queryByRole("combobox", { name: "Search" })).toBeNull();
    fireEvent.keyDown(window, { key: "K", metaKey: true });
    expect(screen.getByRole("combobox", { name: "Search" })).toHaveAttribute("placeholder", "Search tasks, docs, people…");
    fireEvent.keyDown(screen.getByRole("combobox", { name: "Search" }), { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Search (Ctrl+K)" }));
    expect(screen.getByRole("combobox", { name: "Search" })).toBeInTheDocument();
  });

  it("shows nothing before typing", async () => {
    const fetchMock = setup();
    open();
    await new Promise((r) => setTimeout(r, 200));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("groups results in order, with a link to all of them", async () => {
    const fetchMock = setup();
    fireEvent.change(open(), { target: { value: "retyr" } });
    const list = await screen.findByRole("listbox");
    expect(within(list).getAllByRole("heading").map((h) => h.textContent)).toEqual(["Tasks", "Documents", "People", "Agents"]);
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/search/quick?q=retyr");
    const all = screen.getByRole("link", { name: "See all 37 results" });
    expect(all).toHaveAttribute("href", "/search?q=retyr");
  });

  it("arrow keys and Enter open the selected result", async () => {
    setup();
    const box = open();
    fireEvent.change(box, { target: { value: "retry" } });
    await screen.findByRole("listbox");
    expect(screen.getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(box, { key: "ArrowDown" });
    expect(screen.getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(box, { key: "ArrowUp" });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(push).toHaveBeenCalledWith("/projects/PAY/board?task=PAY-42");
    expect(screen.queryByRole("combobox", { name: "Search" })).toBeNull();
  });

  it("people and agents open a card", async () => {
    setup();
    fireEvent.change(open(), { target: { value: "ann" } });
    fireEvent.click(await screen.findByRole("option", { name: /Ann Lee/ }));
    const card = screen.getByRole("region", { name: "Ann Lee" });
    expect(within(card).getByText("ann@acme.io")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Payments" })).toHaveAttribute("href", "/teams/tm1");
    fireEvent.click(screen.getByRole("button", { name: "Back to results" }));
    fireEvent.click(screen.getByRole("option", { name: /Ann's Codex/ }));
    const agent = screen.getByRole("region", { name: "Ann's Codex" });
    expect(within(agent).getByText(/Ann Lee/)).toBeInTheDocument();
    expect(within(agent).getByRole("link", { name: "PAY" })).toHaveAttribute("href", "/projects/PAY/board");
    expect(push).not.toHaveBeenCalled();
  });

  it("renders snippets as text, never as HTML", async () => {
    setup(() =>
      new Response(
        JSON.stringify({ groups: [{ kind: "task", hits: [hit("task", "t1", '<img src=x onerror="alert(1)"> Retry', { url: "/x" })] }], total: 1 }),
        { status: 200 },
      ),
    );
    fireEvent.change(open(), { target: { value: "retry" } });
    const option = await screen.findByRole("option");
    expect(document.querySelector("img")).toBeNull();
    expect(option.textContent).toContain('<img src=x onerror="alert(1)">');
    expect(within(option).getByText("Retry").tagName).toBe("MARK");
  });

  it("says when search is unavailable", async () => {
    setup(() => new Response(JSON.stringify({ detail: "search_unavailable" }), { status: 503 }));
    fireEvent.change(open(), { target: { value: "retry" } });
    expect(await screen.findByText("Search is unavailable right now")).toBeInTheDocument();
  });
});
