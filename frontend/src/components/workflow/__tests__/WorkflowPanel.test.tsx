import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkflowPanel } from "@/components/workflow/WorkflowPanel";
import type { ProjectAgent, Workflow } from "@/lib/types";

const agent = { id: "a1", name: "Ann's Codex", status: "online", can_use: true, owner: { id: "u1", name: "Ann" } } as unknown as ProjectAgent;

function wf(extra: Partial<Workflow> = {}): Workflow {
  return {
    driver: "runner",
    stage: "brainstorm",
    status: "idle",
    needs: null,
    enforcement: "enforced",
    current_step: null,
    steps_total: null,
    escalation_reason: null,
    can_act: true,
    finishing_option: "pull_request",
    branch: null,
    pr_url: null,
    documents: [],
    open_question_id: null,
    steps: [],
    ...extra,
  } as Workflow;
}

function setup(workflow: Workflow, opts: { agent?: ProjectAgent | null; post?: Response } = {}) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method && init.method !== "GET" && opts.post) return opts.post.clone();
    if (url.includes("/agent-runs")) return new Response("[]", { status: 200 });
    return new Response(JSON.stringify(workflow), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkflowPanel taskKey="PAY-1" agent={opts.agent === undefined ? agent : (opts.agent ?? undefined)} disabled={false} />
    </QueryClientProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("WorkflowPanel", () => {
  it("shows Start only for idle agent task with can_use", async () => {
    setup(wf());
    expect(await screen.findByRole("button", { name: "Start" })).toBeInTheDocument();
    expect(screen.getAllByText("Not started").length).toBeGreaterThan(0);
  });

  it("hides Start when the user cannot use the agent", async () => {
    setup(wf(), { agent: { ...agent, can_use: false } });
    await screen.findAllByText("Not started");
    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
  });

  it("escalation shows reason and three actions", async () => {
    setup(wf({ stage: "build", status: "waiting_human", needs: "escalation", escalation_reason: "review_rounds_exhausted" }));
    expect(await screen.findByText("The step still had review findings after 3 review rounds.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
  });

  it("does not offer Accept where it is not allowed", async () => {
    setup(wf({ stage: "build", status: "waiting_human", needs: "escalation", escalation_reason: "retries_exhausted" }));
    expect(await screen.findByText("The agent's runs failed 3 times in a row.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
  });

  it("posts the chosen escalation action", async () => {
    const fetchMock = setup(
      wf({ stage: "build", status: "waiting_human", needs: "escalation", escalation_reason: "review_rounds_exhausted" }),
      { post: new Response(JSON.stringify(wf()), { status: 200 }) },
    );
    fireEvent.click(await screen.findByRole("button", { name: "Accept" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/tasks/PAY-1/workflow/escalation",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ action: "accept" }) }),
      ),
    );
  });

  it("hides decisions from people who cannot act", async () => {
    setup(wf({ stage: "build", status: "waiting_human", needs: "escalation", escalation_reason: "retries_exhausted", can_act: false }));
    await screen.findByText("The agent's runs failed 3 times in a row.");
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("shows Approve PR and the PR link for human code review", async () => {
    setup(wf({ stage: "done", status: "waiting_human", needs: "human_code_review", pr_url: "https://x/pr/1", branch: "task/pay-1" }));
    expect(await screen.findByRole("button", { name: "Approve PR" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /pull request/i })).toHaveAttribute("href", "https://x/pr/1");
    expect(screen.getByText("task/pay-1")).toBeInTheDocument();
  });

  it("shows the finishing select before done", async () => {
    setup(wf({ stage: "build", status: "running" }));
    expect(await screen.findByLabelText("Finishing option")).toBeInTheDocument();
  });

  it("finishing select hidden at done", async () => {
    setup(wf({ stage: "done", status: "running" }));
    await screen.findByText(/Running: Done/);
    expect(screen.queryByLabelText("Finishing option")).not.toBeInTheDocument();
    expect(screen.getByText("Open a pull request")).toBeInTheDocument();
  });

  it("shows the status line and Pause while running", async () => {
    setup(wf({ stage: "build", status: "running", current_step: 2, steps_total: 5 }));
    expect(await screen.findByText("Running: Build, step 2 of 5")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
  });

  it("shows Resume while paused", async () => {
    setup(wf({ stage: "build", status: "paused" }));
    expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();
  });

  it("offers the stage checklist on a human-assigned task", async () => {
    const fetchMock = setup(wf(), { agent: null, post: new Response(JSON.stringify(wf({ driver: "manual" })), { status: 200 }) });
    fireEvent.click(await screen.findByRole("button", { name: "Use stage checklist" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/tasks/PAY-1/workflow",
        expect.objectContaining({ method: "PATCH", body: JSON.stringify({ driver: "manual", stage: "brainstorm" }) }),
      ),
    );
  });

  it("shows stage buttons for a manual workflow", async () => {
    setup(wf({ driver: "manual", stage: "plan" }), { agent: null });
    expect(await screen.findByRole("button", { name: "Build" })).toBeInTheDocument();
  });

  it("shows an error message when an action fails", async () => {
    setup(wf(), { post: new Response(JSON.stringify({ detail: "cannot_use_agent" }), { status: 403 }) });
    fireEvent.click(await screen.findByRole("button", { name: "Start" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You can only use your own agents");
  });
});
