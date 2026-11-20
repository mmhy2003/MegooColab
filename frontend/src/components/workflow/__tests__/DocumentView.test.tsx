import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

type FollowUp = { title: string; type: string; description_md: string; created: boolean; task_key: string | null };
type Place = { column: string; epic: { key: string; title: string } | null };

function setup(
  opts: {
    decision?: Response;
    can_act?: boolean;
    disabled?: boolean;
    kind?: "design" | "plan";
    linked?: boolean;
    followUps?: FollowUp[];
    earlier?: { key: string; title: string }[];
    createsIn?: Place;
  } = {},
) {
  const kind = opts.kind ?? "design";
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/decision")) return (opts.decision ?? new Response("{}", { status: 200 })).clone();
    if (url === "/api/images") {
      return new Response(JSON.stringify({ id: "img-1", filename: "a.png", size: 4, content_type: "image/png" }), { status: 201 });
    }
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
          follow_ups: v === 2 ? (opts.followUps ?? []) : [],
          earlier_follow_ups: v === 2 ? (opts.earlier ?? []) : [],
          creates_in: v === 2 ? (opts.createsIn ?? { column: "To Do", epic: null }) : null,
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

  it("posts a rejection's images with its comment", async () => {
    const fetchMock = setup();
    fireEvent.change(await screen.findByLabelText("Comment"), { target: { value: "like this" } });
    fireEvent.change(document.querySelector<HTMLInputElement>('input[type="file"]')!, {
      target: { files: [new File(["PNG"], "a.png", { type: "image/png" })] },
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/tasks/PAY-1/documents/design/2/decision",
        expect.objectContaining({ body: JSON.stringify({ approve: false, comment: "like this", image_ids: ["img-1"] }) }),
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

  it("marks itself as waiting on the person while they can decide it, and not on a read-only view", async () => {
    setup();
    await screen.findByRole("heading", { name: "Second design" });
    expect(document.body.querySelector('[data-waiting="design"]')).toContainElement(screen.getByRole("button", { name: "Approve" }));
    cleanup();
    setup({ disabled: true });
    await screen.findByRole("heading", { name: "Second design" });
    expect(document.body.querySelector("[data-waiting]")).toBeNull();
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

describe("DocumentView follow-up tasks", () => {
  const proposed: FollowUp[] = [
    { title: "Phase 2: export", type: "story", description_md: "Export the report.", created: false, task_key: null },
    { title: "Phase 3: import", type: "task", description_md: "", created: false, task_key: null },
  ];
  const decisionBody = (fetchMock: ReturnType<typeof setup>) => {
    const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/decision")) as unknown as [string, { body: string }];
    return JSON.parse(call[1].body);
  };

  it("sends the reviewed follow-ups with the approval", async () => {
    const fetchMock = setup({ followUps: proposed });
    fireEvent.click(await screen.findByRole("checkbox", { name: "Create task 2" }));
    fireEvent.click(screen.getByRole("button", { name: "+ Add a task" }));
    fireEvent.change(screen.getByLabelText("Title of task 3"), { target: { value: " Docs " } });
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/decision"))).toBe(true));
    expect(decisionBody(fetchMock)).toEqual({
      approve: true,
      comment: null,
      follow_ups: [
        { title: "Phase 2: export", type: "story", description_md: "Export the report.", create: true },
        { title: "Phase 3: import", type: "task", description_md: "", create: false },
        { title: "Docs", type: "task", description_md: "", create: true },
      ],
    });
  });

  it("blocks approval when a ticked task has no title", async () => {
    const fetchMock = setup({ followUps: proposed });
    fireEvent.click(await screen.findByRole("button", { name: "+ Add a task" }));
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Give every ticked task a title.");
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/decision"))).toBe(false);
  });

  it("says what approving creates", async () => {
    setup({ followUps: proposed });
    expect(await screen.findByText("Approving creates 2 tasks in To Do, unassigned.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Create task 1" }));
    expect(screen.getByText("Approving creates 1 task in To Do, unassigned.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Create task 2" }));
    expect(screen.getByText("Approving creates no tasks.")).toBeInTheDocument();
    cleanup();
    setup({ followUps: proposed, createsIn: { column: "To Do", epic: { key: "PAY-3", title: "Payments" } } });
    expect(await screen.findByText("Approving creates 2 tasks in To Do, in epic PAY-3, unassigned.")).toBeInTheDocument();
  });

  it("read-only for someone who cannot decide", async () => {
    setup({ followUps: proposed, can_act: false });
    expect(await screen.findByText(/Phase 2: export/)).toBeInTheDocument();
    expect(screen.getByText(/Phase 3: import/)).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/Approving creates/)).not.toBeInTheDocument();
  });

  it("shows earlier tasks", async () => {
    setup({ earlier: [{ key: "PAY-7", title: "Phase 2" }, { key: "PAY-8", title: "Phase 3" }] });
    expect(await screen.findByText(/Already created from an earlier approved design:/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "PAY-7" })).toHaveAttribute("href", "/projects/PAY/board?task=PAY-7");
    expect(screen.getByRole("link", { name: "PAY-8" })).toBeInTheDocument();
  });

  it("a rejection sends no follow-ups", async () => {
    const fetchMock = setup({ followUps: proposed });
    fireEvent.change(await screen.findByLabelText("Comment"), { target: { value: "split differently" } });
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/decision"))).toBe(true));
    expect(decisionBody(fetchMock)).toEqual({ approve: false, comment: "split differently" });
  });

  it("shows None proposed to a decider when the list is empty", async () => {
    setup();
    expect(await screen.findByText("None proposed.")).toBeInTheDocument();
    expect(screen.getByText("Approving creates no tasks.")).toBeInTheDocument();
  });

  it("a plan shows no follow-up block and sends no follow-ups", async () => {
    const fetchMock = setup({ kind: "plan" });
    await screen.findByText("Add model");
    expect(screen.queryByRole("region", { name: "Follow-up tasks" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/decision"))).toBe(true));
    expect(decisionBody(fetchMock)).toEqual({ approve: true, comment: null });
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
        testRun("base", 1, false, { total: 5, failed: 1, failing: ["test_old"], baseline: true, created_at: "2026-10-27T10:00:00Z" }),
        testRun("a", 1, false, { total: 5, failed: 1, failing: ["test_x"], created_at: "2026-10-27T10:01:00Z" }),
        testRun("b", 1, true, { total: 5, failed: 0, created_at: "2026-10-27T10:02:00Z" }),
        testRun("d", 2, false, {
          total: 6, failed: 2, failing: ["test_old", "test_y"], marks: ["baseline", "new"], created_at: "2026-10-27T10:02:30Z",
        }),
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

  it("shows the test baseline above the steps, and not among step 1's runs", async () => {
    setupPlan();
    const box = await screen.findByRole("region", { name: "Test baseline" });
    expect(within(box).getByText("Test baseline (before step 1) · 1 already failing — uv run pytest")).toBeInTheDocument();
    expect(within(box).getByText("test_old")).toBeInTheDocument();
    const step1 = screen.getByText("Add model", { selector: "span" }).closest("li") as HTMLElement;
    expect(box.nextElementSibling).toBe(step1.closest("ol"));
    expect(within(step1).getByText("✓ 5 passed — uv run pytest")).toBeInTheDocument();
    expect(within(step1).getByText("Earlier runs (1)")).toBeInTheDocument();
    expect(within(step1).queryByText(/test_old/)).not.toBeInTheDocument();
  });

  it("marks a step run's new failures", async () => {
    setupPlan();
    const line = await screen.findByText("✗ 2 failed, 1 new — uv run pytest");
    const step2 = line.closest("li") as HTMLElement;
    expect(step2).toHaveTextContent("Add API");
    expect(within(step2).getByText("new", { exact: true })).toBeInTheDocument();
    expect(within(step2).getByText("also fails in the baseline", { exact: true })).toBeInTheDocument();
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
