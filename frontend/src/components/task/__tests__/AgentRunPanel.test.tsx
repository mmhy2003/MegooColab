import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentRunPanel } from "@/components/task/AgentRunPanel";
import type { ProjectAgent, AgentRun } from "@/lib/types";

const agent = {
  id: "a1",
  name: "Ann's Codex",
  program: "codex",
  status: "offline",
  can_use: true,
  owner: { id: "u1", name: "Ann Lee" },
} as unknown as ProjectAgent;

function run(status: AgentRun["status"], extra: Partial<AgentRun> = {}): AgentRun {
  return {
    id: "r1",
    task_key: "PAY-1",
    agent: { id: "a1", name: "Ann's Codex", program: "codex" },
    policy: "read_only",
    status,
    reason: null,
    summary: null,
    created_at: "2026-10-22T10:00:00Z",
    started_at: null,
    finished_at: null,
    ...extra,
  } as AgentRun;
}

function setup(agentArg: ProjectAgent, runs: AgentRun[], post?: Response) {
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
    init?.method === "POST" && post
      ? post
      : new Response(JSON.stringify(init?.method === "POST" ? runs[0] ?? {} : runs), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AgentRunPanel taskKey="PAY-1" agent={agentArg} disabled={false} />
    </QueryClientProvider>,
  );
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("AgentRunPanel", () => {
  it("shows the offline note with the owner's name when the agent is offline", async () => {
    setup(agent, []);
    expect(await screen.findByText("Agent offline — the run starts when Ann Lee's runner connects.")).toBeInTheDocument();
  });

  it("omits the offline note when the agent is online", async () => {
    setup({ ...agent, status: "online" }, []);
    await screen.findByRole("button", { name: "Run agent" });
    expect(screen.queryByText(/Agent offline/)).not.toBeInTheDocument();
  });

  it("posts the chosen policy and prompt", async () => {
    const fetchMock = setup(agent, []);
    await screen.findByRole("button", { name: "Run agent" });
    fireEvent.change(screen.getByLabelText("Run policy"), { target: { value: "workspace" } });
    fireEvent.change(screen.getByLabelText("Prompt (optional)"), { target: { value: "Fix the flaky test" } });
    fireEvent.click(screen.getByRole("button", { name: "Run agent" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, i]) => i?.method === "POST")).toBe(true));
    const [url, init] = fetchMock.mock.calls.find(([, i]) => i?.method === "POST")!;
    expect(url).toBe("/api/tasks/PAY-1/agent-runs");
    expect(JSON.parse(String(init!.body))).toEqual({ policy: "workspace", prompt: "Fix the flaky test" });
  });

  it("disables Run agent when the caller cannot use the agent", async () => {
    setup({ ...agent, can_use: false }, []);
    expect(await screen.findByRole("button", { name: "Run agent" })).toBeDisabled();
  });

  it.each(["queued", "running"] as const)("offers Cancel for a %s run", async (status) => {
    setup(agent, [run(status)]);
    expect(await screen.findByRole("button", { name: "Cancel run" })).toBeInTheDocument();
  });

  it.each(["queued", "running"] as const)("disables Run agent while the latest run is %s", async (status) => {
    setup(agent, [run(status)]);
    await screen.findByRole("button", { name: "Cancel run" });
    expect(screen.getByRole("button", { name: "Run agent" })).toBeDisabled();
  });

  it("enables Run agent again once the latest run has ended", async () => {
    setup(agent, [run("completed")]);
    await screen.findByText(/completed/);
    expect(screen.getByRole("button", { name: "Run agent" })).toBeEnabled();
  });

  it("shows a failed run's reason in plain words", async () => {
    setup(agent, [run("failed", { reason: "runner_disconnected" })]);
    expect(await screen.findByText("failed · read-only · the runner disconnected")).toBeInTheDocument();
  });

  it("explains a start that raced another run", async () => {
    const conflict = new Response(JSON.stringify({ detail: "task_has_active_run" }), { status: 409 });
    setup(agent, [], conflict);
    fireEvent.click(await screen.findByRole("button", { name: "Run agent" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This task already has an agent run in progress. Wait for it to finish, or cancel it first.",
    );
  });

  it.each(["completed", "failed", "cancelled"] as const)("hides Cancel for a %s run and shows its summary", async (status) => {
    setup(agent, [run(status, { summary: "All done" })]);
    expect(await screen.findByText(/All done/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
  });
});
