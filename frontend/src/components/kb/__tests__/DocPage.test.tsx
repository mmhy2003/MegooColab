import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ docId: "d1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams("edit=1"),
}));

import KbDocumentPage from "@/app/(app)/kb/doc/[docId]/page";
import { kbKeys } from "@/lib/kb";

const DOC = {
  id: "d1",
  space: { id: "s1", kind: "team", name: "Core" },
  folder_id: null,
  path: "",
  title: "Webhooks",
  body_md: "Body",
  latest_revision: 2,
  created_by: "u1",
  updated_at: "2026-10-26T10:00:00Z",
  updated_by: { user: { id: "u1", name: "Ann" }, agent: null },
  can_write: true,
  can_delete: true,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("KbDocumentPage", () => {
  it("keeps the editor and the draft when a refetch fails", async () => {
    let gone = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === "/api/kb/documents/d1") {
          return gone
            ? new Response(JSON.stringify({ detail: "document_not_found" }), { status: 404 })
            : new Response(JSON.stringify(DOC), { status: 200 });
        }
        return new Response("{}", { status: 200 });
      }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <KbDocumentPage />
      </QueryClientProvider>,
    );
    fireEvent.change(await screen.findByLabelText("Body"), { target: { value: "My unsaved draft" } });
    gone = true;
    await act(() => client.refetchQueries({ queryKey: kbKeys.doc("d1") }));
    expect(screen.getByLabelText("Body")).toHaveValue("My unsaved draft");
    expect(await screen.findByRole("alert")).toHaveTextContent(/no longer available/);
    expect(screen.getByLabelText("Body")).toHaveValue("My unsaved draft"); // still mounted once the error shows
  });
});
