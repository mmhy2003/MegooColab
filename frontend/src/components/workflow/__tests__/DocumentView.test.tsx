import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DocumentView } from "@/components/workflow/DocumentView";

const info = (version: number, status: string) => ({
  kind: "design",
  version,
  status,
  created_at: "2026-10-25T10:00:00Z",
  decided_by: null,
  decision_comment: null,
});

function setup(opts: { decision?: Response; can_act?: boolean; disabled?: boolean; kind?: "design" | "plan" } = {}) {
  const kind = opts.kind ?? "design";
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/decision")) return (opts.decision ?? new Response("{}", { status: 200 })).clone();
    if (url.endsWith("/mockups")) return new Response(JSON.stringify([{ id: "m1", version: 3 }]), { status: 200 });
    if (url.endsWith("/workflow")) {
      return new Response(JSON.stringify({ can_act: opts.can_act ?? true, steps: [], documents: [] }), { status: 200 });
    }
    if (/documents\/\w+\/\d+$/.test(url)) {
      const v = Number(url.split("/").pop());
      return new Response(
        JSON.stringify({
          ...info(v, v === 2 ? "submitted" : "superseded"),
          kind,
          body_md: v === 2 ? "# Second design" : "# First design",
          steps: kind === "plan" ? [{ title: "Add model", detail: "d", subtask_id: null }] : null,
          attached_mockup_ids: v === 2 ? ["m1"] : [],
        }),
        { status: 200 },
      );
    }
    return new Response(JSON.stringify([info(1, "superseded"), info(2, "submitted")].map((d) => ({ ...d, kind }))), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DocumentView taskKey="PAY-1" kind={kind} disabled={opts.disabled} />
    </QueryClientProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  window.location.hash = "";
  cleanup();
  vi.unstubAllGlobals();
});

describe("DocumentView", () => {
  it("lists versions, renders the latest as markdown and links the mockup", async () => {
    setup();
    expect(await screen.findByRole("heading", { name: "Second design" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /v1/ })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Chosen mockup v3" })).toHaveAttribute("href", "/api/mockups/m1/view");
  });

  it("selects the version named by the link hash, now and when it changes", async () => {
    window.location.hash = "#document-design-v1";
    setup();
    expect(await screen.findByRole("heading", { name: "First design" })).toBeInTheDocument();
    window.location.hash = "#document-design-v2";
    expect(await screen.findByRole("heading", { name: "Second design" })).toBeInTheDocument();
    window.location.hash = "#document-plan-v1"; // another kind: unchanged
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.getByRole("heading", { name: "Second design" })).toBeInTheDocument();
  });

  it("renders plan steps as a numbered list", async () => {
    setup({ kind: "plan" });
    expect(await screen.findByText("Add model")).toBeInTheDocument();
    expect(screen.getByText("Add model").closest("ol")).not.toBeNull();
  });

  it("reject requires comment", async () => {
    const fetchMock = setup();
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Add a comment explaining what should change.");
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/decision"))).toBe(false);
  });

  it("posts a rejection with its comment", async () => {
    const fetchMock = setup();
    fireEvent.change(await screen.findByLabelText("Comment"), { target: { value: "too vague" } });
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/tasks/PAY-1/documents/design/2/decision",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ approve: false, comment: "too vague" }) }),
      ),
    );
  });

  it("409 shows already-decided message", async () => {
    setup({ decision: new Response(JSON.stringify({ detail: "already_decided" }), { status: 409 }) });
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Someone already decided this version.");
  });

  it("shows no decision buttons on a read-only view", async () => {
    setup({ disabled: true });
    await screen.findByRole("heading", { name: "Second design" });
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("marks the selected version in text, not only colour", async () => {
    setup();
    await screen.findByRole("heading", { name: "Second design" });
    expect(screen.getByRole("button", { name: /v2.*\(selected\)/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /v1/ })).not.toHaveTextContent("(selected)");
  });

  it("hides the decision for people who cannot act", async () => {
    setup({ can_act: false });
    await screen.findByRole("heading", { name: "Second design" });
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });
});
