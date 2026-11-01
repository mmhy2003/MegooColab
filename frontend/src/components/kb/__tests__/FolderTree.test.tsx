import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DocList } from "@/components/kb/DocList";
import { FolderTree } from "@/components/kb/FolderTree";
import { invalidationsFor } from "@/lib/realtime";
import { answer } from "@/test/answer";

const FOLDERS = [
  { id: "f1", parent_id: null, name: "Guides" },
  { id: "f2", parent_id: "f1", name: "API" },
  { id: "f3", parent_id: null, name: "Empty" },
];
const DOCS = [
  { id: "d1", folder_id: "f2", title: "Webhooks", latest_revision: 3, updated_at: "2026-10-20T10:00:00Z" },
  { id: "d2", folder_id: null, title: "Readme", latest_revision: 1, updated_at: "2026-10-21T10:00:00Z" },
];

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("FolderTree", () => {
  it("renders nesting and selection", () => {
    const onSelect = vi.fn();
    wrap(<FolderTree spaceId="s1" folders={FOLDERS} documents={DOCS} selected="f2" onSelect={onSelect} canWrite />);
    const tree = screen.getByRole("tree");
    const guides = within(tree).getByRole("treeitem", { name: /Guides/ });
    // children render inside their parent's group
    expect(within(guides).getByRole("treeitem", { name: /API/ })).toHaveAttribute("aria-selected", "true");
    expect(within(tree).getByRole("treeitem", { name: /Empty/ })).toHaveAttribute("aria-selected", "false");
    fireEvent.click(within(tree).getByRole("button", { name: "Empty" }));
    expect(onSelect).toHaveBeenCalledWith("f3");
    fireEvent.click(within(tree).getByRole("button", { name: "All documents" }));
    expect(onSelect).toHaveBeenCalledWith(null);
    // collapse hides the children
    fireEvent.click(within(guides).getByRole("button", { name: "Collapse Guides" }));
    expect(within(tree).queryByRole("treeitem", { name: /API/ })).not.toBeInTheDocument();
  });

  it("delete non-empty folder asks and sends recursive", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    const onSelect = vi.fn();
    wrap(<FolderTree spaceId="s1" folders={FOLDERS} documents={DOCS} selected="f1" onSelect={onSelect} canWrite />);
    fireEvent.click(screen.getByRole("button", { name: "Delete folder Guides" }));
    expect(await screen.findByRole("alertdialog")).toHaveAccessibleDescription(/documents inside move up/);
    await answer("Delete");
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect((fetchMock.mock.calls[0] as unknown[])[0]).toBe("/api/kb/folders/f1?recursive=true");
    expect(onSelect).toHaveBeenCalledWith(null);

    fetchMock.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Delete folder Empty" }));
    expect(await screen.findByRole("alertdialog")).toHaveAccessibleName("Delete folder Empty?");
    await answer("Delete");
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect((fetchMock.mock.calls[0] as unknown[])[0]).toBe("/api/kb/folders/f3");
  });

  it("creates and renames folders", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: "f9", parent_id: "f1", name: "New" }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    wrap(<FolderTree spaceId="s1" folders={FOLDERS} documents={DOCS} selected="f1" onSelect={vi.fn()} canWrite />);
    fireEvent.click(screen.getByRole("button", { name: "New folder" }));
    fireEvent.change(screen.getByLabelText("Folder name"), { target: { value: "New" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/kb/spaces/s1/folders");
    expect(JSON.parse(init.body as string)).toEqual({ name: "New", parent_id: "f1" });

    fetchMock.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Rename folder Guides" }));
    const field = await screen.findByRole("textbox", { name: "Folder name" });
    expect(field).toHaveValue("Guides");
    fireEvent.change(field, { target: { value: "Docs" } });
    await answer("Rename");
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [rurl, rinit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(rurl).toBe("/api/kb/folders/f1");
    expect(JSON.parse(rinit.body as string)).toEqual({ name: "Docs" });
  });

  it("lists documents under their folders and marks the current one", () => {
    localStorage.clear();
    wrap(<FolderTree spaceId="s1" folders={FOLDERS} documents={DOCS} selected={null} currentDocId="d1" onSelect={vi.fn()} canWrite={false} />);
    const tree = screen.getByRole("tree");
    const api = within(tree).getByRole("treeitem", { name: "API" });
    const webhooks = within(api).getByRole("link", { name: "Webhooks" });
    expect(webhooks).toHaveAttribute("href", "/kb/doc/d1");
    expect(webhooks).toHaveAttribute("aria-current", "page");
    // the top level's documents come after its folders
    const top = within(tree).getByRole("link", { name: "Readme" });
    expect(top).toHaveAttribute("href", "/kb/doc/d2");
    expect(top).not.toHaveAttribute("aria-current");
    // reading a document, the top level isn't the selected place
    expect(within(tree).getByRole("treeitem", { name: "All documents" })).toHaveAttribute("aria-selected", "false");
  });

  it("opens the path to the current document and remembers folders opened by hand", () => {
    localStorage.clear();
    const { unmount } = wrap(
      <FolderTree spaceId="s1" folders={[...FOLDERS, { id: "f4", parent_id: "f3", name: "Inner" }]} documents={DOCS} selected={null} currentDocId="d2" onSelect={vi.fn()} canWrite={false} />,
    );
    const tree = screen.getByRole("tree");
    // never opened: closed
    expect(within(tree).queryByRole("treeitem", { name: "API" })).toBeNull();
    fireEvent.click(within(tree).getByRole("button", { name: "Expand Guides" }));
    expect(within(tree).getByRole("treeitem", { name: "API" })).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("kb.open.s1")!)).toEqual(["f1"]);
    unmount();
    wrap(<FolderTree spaceId="s1" folders={FOLDERS} documents={DOCS} selected={null} onSelect={vi.fn()} canWrite={false} />);
    expect(within(screen.getByRole("tree")).getByRole("treeitem", { name: "API" })).toBeInTheDocument();
  });

  it("ignores remembered folders that no longer exist", () => {
    localStorage.setItem("kb.open.s1", JSON.stringify(["gone", "f1"]));
    wrap(<FolderTree spaceId="s1" folders={FOLDERS} documents={DOCS} selected={null} onSelect={vi.fn()} canWrite={false} />);
    expect(within(screen.getByRole("tree")).getByRole("treeitem", { name: "API" })).toBeInTheDocument();
    localStorage.clear();
  });

  it("works when storage throws", () => {
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    wrap(<FolderTree spaceId="s1" folders={FOLDERS} documents={DOCS} selected={null} currentDocId="d1" onSelect={vi.fn()} canWrite={false} />);
    expect(within(screen.getByRole("tree")).getByRole("link", { name: "Webhooks" })).toBeInTheDocument();
    get.mockRestore();
    set.mockRestore();
  });

  it("scrolls the current document into view once its folders open", () => {
    localStorage.clear();
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    wrap(<FolderTree spaceId="s1" folders={FOLDERS} documents={DOCS} selected={null} currentDocId="d1" onSelect={vi.fn()} canWrite={false} />);
    expect(scroll).toHaveBeenCalled();
    expect(scroll.mock.contexts.at(-1)).toHaveAttribute("aria-label", "Webhooks");
    Reflect.deleteProperty(Element.prototype, "scrollIntoView");
  });

  it("a remembered value of another shape is ignored", () => {
    localStorage.setItem("kb.open.s1", JSON.stringify({ f1: true }));
    wrap(<FolderTree spaceId="s1" folders={FOLDERS} documents={DOCS} selected={null} onSelect={vi.fn()} canWrite={false} />);
    expect(screen.getByRole("tree")).toBeInTheDocument();
  });

  it("no write actions without can_write", () => {
    wrap(<FolderTree spaceId="s1" folders={FOLDERS} documents={DOCS} selected={null} onSelect={vi.fn()} canWrite={false} />);
    expect(screen.queryByRole("button", { name: "New folder" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete folder/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Rename folder/ })).not.toBeInTheDocument();
  });
});

describe("DocList", () => {
  it("shows updated dates and opens doc", () => {
    wrap(<DocList documents={DOCS} folderId="f2" />);
    const link = screen.getByRole("link", { name: /Webhooks/ });
    expect(link).toHaveAttribute("href", "/kb/doc/d1");
    expect(screen.getByText(new Date("2026-10-20T10:00:00Z").toLocaleDateString())).toBeInTheDocument();
    expect(screen.getByText("rev 3")).toBeInTheDocument();
    expect(screen.queryByText("Readme")).not.toBeInTheDocument();
  });

  it("shows root documents and an empty state", () => {
    const { unmount } = wrap(<DocList documents={DOCS} folderId={null} />);
    expect(screen.getByRole("link", { name: /Readme/ })).toBeInTheDocument();
    unmount();
    wrap(<DocList documents={[]} folderId={null} />);
    expect(screen.getByText("No documents here yet.")).toBeInTheDocument();
  });
});

describe("realtime", () => {
  it("kb.updated invalidates kb queries", () => {
    expect(invalidationsFor({ type: "kb.updated", space_id: "s1" }, new Map())).toEqual([["kb"]]);
  });
});
