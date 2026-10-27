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

function setup(opts: { decision?: Response; can_act?: boolean; disabled?: boolean; kind?: "design" | "plan"; linked?: boolean } = {}) {
  const kind = opts.kind ?? "design";
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/decision")) return (opts.decision ?? new Response("{}", { status: 200 })).clone();
    if (url.endsWith("/mockups")) return new Response(JSON.stringify([{ id: "m1", version: 3, title: "Compact", choices: [] }]), { status: 200 });
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
          mockup_id: v === 2 && opts.linked ? "m1" : null,
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

  it("shows the design's linked mockup inline", async () => {
    setup({ linked: true });
    expect(await screen.findByTitle("Mockup v3: Compact")).toHaveAttribute("src", "/api/mockups/m1/view");
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

  it("any other 409 shows its own message", async () => {
    setup({ decision: new Response(JSON.stringify({ detail: "not_waiting_for_decision" }), { status: 409 }) });
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The workflow isn't waiting for that decision right now.");
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

describe("DocumentView recorded test runs", () => {
  const testRun = (id: string, step: number | null, passed: boolean, extra: Record<string, unknown> = {}) => ({
    id, stage: step === null ? "done" : "build", step, command: "uv run pytest", passed, total: null, failed: null,
    skipped: null, failing: [], author: "Bot", created_at: `2026-10-27T10:0${id.length}:00Z`, ...extra,
  });

  function setupPlan() {
    const records = {
      decisions: [],
      test_runs: [
        testRun("a", 1, false, { total: 5, failed: 1, failing: ["test_x"], created_at: "2026-10-27T10:01:00Z" }),
        testRun("b", 1, true, { total: 5, failed: 0, created_at: "2026-10-27T10:02:00Z" }),
        testRun("c", null, true, { total: 12, failed: 0, created_at: "2026-10-27T10:03:00Z" }),
      ],
      unverified_steps: [2],
    };
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith("/records")) return new Response(JSON.stringify(records), { status: 200 });
      if (url.endsWith("/mockups")) return new Response("[]", { status: 200 });
      if (url.endsWith("/workflow")) {
        return new Response(
          JSON.stringify({ can_act: true, documents: [], steps: [{ n: 1, title: "Add model", state: "done" }, { n: 2, title: "Add API", state: "done" }] }),
          { status: 200 },
        );
      }
      if (/documents\/plan\/1$/.test(url)) {
        return new Response(
          JSON.stringify({
            ...info(1, "approved"), kind: "plan", body_md: "# Plan", attached_mockup_ids: [], mockup_id: null,
            steps: [{ title: "Add model", detail: "", subtask_id: null }, { title: "Add API", detail: "", subtask_id: null }],
          }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify([{ ...info(1, "approved"), kind: "plan" }]), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <DocumentView taskKey="PAY-1" kind="plan" />
      </QueryClientProvider>,
    );
  }

  it("shows each step's latest test run, with earlier runs behind a disclosure", async () => {
    setupPlan();
    expect(await screen.findByText("✓ 5 passed — uv run pytest")).toBeInTheDocument();
    expect(screen.getByText("Earlier runs (1)")).toBeInTheDocument();
    expect(screen.getByText("✗ 1 failed: test_x — uv run pytest")).toBeInTheDocument();
  });

  it("warns on a step that claims passing tests without a recorded run", async () => {
    setupPlan();
    const warning = await screen.findByText("No test run recorded");
    expect(warning.closest("li")).toHaveTextContent("Add API");
  });

  it("shows the finish verification under the steps", async () => {
    setupPlan();
    expect(await screen.findByText("Finish verification: ✓ 12 passed — uv run pytest")).toBeInTheDocument();
  });
});
