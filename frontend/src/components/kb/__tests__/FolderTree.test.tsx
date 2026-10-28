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
