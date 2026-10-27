import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MockupPanel } from "@/components/workflow/MockupPanel";
import { qk } from "@/lib/queries";

const mockup = (version: number) => ({
  id: `m${version}`,
  version,
  title: `Layout ${version}`,
  choices: [],
  created_at: `2026-10-27T10:0${version}:00Z`,
});

const doc = (version: number, status: string, mockup_id: string | null) => ({
  kind: "design",
  version,
  status,
  created_at: "2026-10-27T10:00:00Z",
  decided_by: null,
  decision_comment: null,
  mockup_id,
});

type State = {
  mockups: ReturnType<typeof mockup>[];
  workflow?: Record<string, unknown>;
  documents?: ReturnType<typeof doc>[];
  decision?: Response;
};

function setup(state: State) {
  const workflow = { can_act: true, status: "running", needs: null, open_question_id: null, steps: [], documents: [], ...state.workflow };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      if (url.endsWith("/decision") && state.decision) return state.decision.clone();
      return new Response("{}", { status: 200 });
    }
    if (url.endsWith("/mockups")) return new Response(JSON.stringify(state.mockups), { status: 200 });
    if (url.endsWith("/workflow")) return new Response(JSON.stringify(workflow), { status: 200 });
    if (url.endsWith("/documents")) return new Response(JSON.stringify(state.documents ?? []), { status: 200 });
    return new Response("{}", { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MockupPanel taskKey="PAY-1" />
    </QueryClientProvider>,
  );
  const posts = () => fetchMock.mock.calls.filter(([, i]) => i?.method === "POST").map(([u, i]) => [u, JSON.parse(String(i!.body))]);
  return { client, fetchMock, posts };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("MockupPanel", () => {
  it("shows the newest version and switches versions", async () => {
    setup({ mockups: [mockup(1), mockup(2)] });
    expect(await screen.findByTitle("Mockup v2: Layout 2")).toBeInTheDocument();
    expect(screen.getByText("v2 of 2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    expect(screen.getByTitle("Mockup v1: Layout 1")).toBeInTheDocument();
    expect(screen.queryByTitle("Mockup v2: Layout 2")).toBeNull();
  });

  it("does not move a viewer off an older version when a new one arrives", async () => {
    const state: State = { mockups: [mockup(1), mockup(2)] };
    const { client } = setup(state);
    expect(await screen.findByTitle("Mockup v2: Layout 2")).toBeInTheDocument();
    // following the newest: v3 replaces v2
    state.mockups = [mockup(1), mockup(2), mockup(3)];
    await client.invalidateQueries({ queryKey: qk.mockups("PAY-1") });
    expect(await screen.findByTitle("Mockup v3: Layout 3")).toBeInTheDocument();
    // looking at v1: v4 does not take the frame, a pill offers it
    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    state.mockups = [...state.mockups, mockup(4)];
    await client.invalidateQueries({ queryKey: qk.mockups("PAY-1") });
    const pill = await screen.findByRole("button", { name: "v4 is ready" });
    expect(screen.getByTitle("Mockup v1: Layout 1")).toBeInTheDocument();
    fireEvent.click(pill);
    expect(screen.getByTitle("Mockup v4: Layout 4")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /is ready/ })).toBeNull();
  });

  it("compares two versions side by side", async () => {
    setup({ mockups: [mockup(1), mockup(2)] });
    await screen.findByTitle("Mockup v2: Layout 2");
    fireEvent.change(screen.getByLabelText("Compare with"), { target: { value: "1" } });
    expect(screen.getByTitle("Mockup v1: Layout 1")).toBeInTheDocument();
    expect(screen.getByTitle("Mockup v2: Layout 2")).toBeInTheDocument();
  });

  it("feedback answers the open question", async () => {
    const { posts } = setup({ mockups: [mockup(1)], workflow: { status: "waiting_human", needs: "question", open_question_id: "q1" } });
    fireEvent.change(await screen.findByLabelText("Feedback"), { target: { value: "Bigger header" } });
    fireEvent.click(screen.getByRole("button", { name: "Send feedback" }));
    await waitFor(() => expect(posts()).toEqual([["/api/tasks/PAY-1/questions/q1/answer", { text: "Bigger header" }]]));
  });

  it("feedback requests changes to a design awaiting approval", async () => {
    const { posts } = setup({
      mockups: [mockup(1)],
      workflow: { status: "waiting_human", needs: "design_approval" },
      documents: [doc(1, "rejected", null), doc(2, "submitted", "m1")],
    });
    fireEvent.click(await screen.findByRole("button", { name: "Request changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Add a comment explaining what should change.");
    expect(posts()).toEqual([]);
    fireEvent.change(screen.getByLabelText("Feedback"), { target: { value: "Bigger header" } });
    fireEvent.click(screen.getByRole("button", { name: "Request changes" }));
    await waitFor(() =>
      expect(posts()).toEqual([["/api/tasks/PAY-1/documents/design/2/decision", { approve: false, comment: "Bigger header" }]]),
    );
  });

  it("feedback is disabled while the agent works", async () => {
    setup({ mockups: [mockup(1)], workflow: { status: "running" } });
    expect(await screen.findByLabelText("Feedback")).toBeDisabled();
    expect(screen.getByText("The agent is working. You can reply when it asks a question or submits the design.")).toBeInTheDocument();
  });

  it("approves the design only from the version it was submitted with", async () => {
    const { posts } = setup({
      mockups: [mockup(1), mockup(2), mockup(3)],
      workflow: { status: "waiting_human", needs: "design_approval" },
      documents: [doc(2, "submitted", "m3")],
    });
    fireEvent.click(await screen.findByRole("button", { name: "Approve this version" }));
    await waitFor(() => expect(posts()).toEqual([["/api/tasks/PAY-1/documents/design/2/decision", { approve: true, comment: null }]]));
    fireEvent.click(screen.getByRole("button", { name: "v2" }));
    expect(screen.getByText("Older version")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve this version" })).toBeNull();
  });

  it("offers no approval to someone who cannot act", async () => {
    setup({
      mockups: [mockup(1)],
      workflow: { can_act: false, status: "waiting_human", needs: "design_approval" },
      documents: [doc(1, "submitted", "m1")],
    });
    await screen.findByTitle("Mockup v1: Layout 1");
    expect(screen.queryByRole("button", { name: "Approve this version" })).toBeNull();
    expect(screen.queryByLabelText("Feedback")).toBeNull();
  });

  it("says when someone already decided", async () => {
    setup({
      mockups: [mockup(1)],
      workflow: { status: "waiting_human", needs: "design_approval" },
      documents: [doc(1, "submitted", "m1")],
      decision: new Response(JSON.stringify({ detail: "already_decided" }), { status: 409 }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Approve this version" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Someone already decided this version.");
  });

  it("renders nothing without mockups", async () => {
    const { fetchMock } = setup({ mockups: [] });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.queryByText(/of \d/)).toBeNull();
  });
});
