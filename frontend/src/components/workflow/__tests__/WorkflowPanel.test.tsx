import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    finishing_forced: false,
    can_set_manual: false,
    branch: null,
    pr_url: null,
    documents: [],
    open_question_id: null,
    steps: [],
    ...extra,
  } as Workflow;
}

function setup(
  workflow: Workflow,
  opts: { runs?: unknown[]; agent?: ProjectAgent | null; post?: Response; unassigned?: boolean; disabled?: boolean; decisions?: unknown[] } = {},
) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method && init.method !== "GET" && opts.post) return opts.post.clone();
    if (url.endsWith("/records")) {
      return new Response(JSON.stringify({ decisions: opts.decisions ?? [], test_runs: [], unverified_steps: [] }), { status: 200 });
    }
    if (url.includes("/agent-runs")) return new Response(JSON.stringify(opts.runs ?? []), { status: 200 });
    return new Response(JSON.stringify(workflow), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkflowPanel taskKey="PAY-1" agent={opts.agent === undefined ? agent : (opts.agent ?? undefined)} unassigned={opts.unassigned ?? opts.agent === null} disabled={opts.disabled ?? false} />
    </QueryClientProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("WorkflowPanel", () => {
  it("links to the agent's decisions when there are some", async () => {
    setup(wf({ status: "running", stage: "build" }), { decisions: [{ id: "d1" }, { id: "d2" }] });
    expect(await screen.findByRole("link", { name: "2 decisions" })).toHaveAttribute("href", "#decisions");
  });

  it("shows no decisions link without decisions", async () => {
    setup(wf({ status: "running", stage: "build" }));
    await screen.findAllByText(/Build/);
    expect(screen.queryByRole("link", { name: /decision/ })).toBeNull();
  });

  it("shows Start only for idle agent task with can_use", async () => {
    setup(wf());
    expect(await screen.findByRole("button", { name: "Start" })).toBeInTheDocument();
    expect(screen.getAllByText("Not started")).toHaveLength(1);
  });

  it("hides Start when the user cannot use the agent", async () => {
    setup(wf(), { agent: { ...agent, can_use: false } });
    await screen.findByText("Not started");
    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
  });

  it("escalation shows reason and three actions", async () => {
    setup(wf({ stage: "build", status: "waiting_human", needs: "escalation", escalation_reason: "review_rounds_exhausted" }));
    expect(await screen.findByText("The step still had review findings after 3 review rounds.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
  });

  it("marks an escalation and a code review as waiting on the person", async () => {
    setup(wf({ stage: "build", status: "waiting_human", needs: "escalation", escalation_reason: "review_rounds_exhausted" }));
    await screen.findByRole("button", { name: "Retry" });
    expect(document.body.querySelector('[data-waiting="escalation"]')).toContainElement(screen.getByRole("button", { name: "Retry" }));
    cleanup();
    setup(wf({ stage: "done", status: "waiting_human", needs: "human_code_review", pr_url: "https://x/pr/1", branch: "task/pay-1" }));
    await screen.findByRole("button", { name: "Mark merged" });
    expect(document.body.querySelector('[data-waiting="code_review"]')).toContainElement(screen.getByRole("button", { name: "Mark merged" }));
  });

  it("a closed pull request can be accepted as finished", async () => {
    setup(wf({ stage: "done", status: "waiting_human", needs: "escalation", escalation_reason: "pr_closed" }));
    expect(await screen.findByText("The pull request was closed without being merged.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument();
  });

  it("says when it was the back-merge pull request that closed", async () => {
    setup(wf({ stage: "done", status: "waiting_human", needs: "escalation", escalation_reason: "back_merge_pr_closed" }));
    expect(
      await screen.findByText("The back-merge pull request (into the default branch) was closed without being merged."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument();
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

  it("shows Mark merged and the PR link for human code review", async () => {
    setup(wf({ stage: "done", status: "waiting_human", needs: "human_code_review", pr_url: "https://x/pr/1", branch: "task/pay-1" }));
    expect(await screen.findByRole("button", { name: "Mark merged" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /pull request/i })).toHaveAttribute("href", "https://x/pr/1");
    expect(screen.getByText("task/pay-1")).toBeInTheDocument();
  });

  it("shows the finishing select before done", async () => {
    setup(wf({ stage: "build", status: "running" }));
    expect(await screen.findByLabelText("Finishing option")).toBeInTheDocument();
    // what the chosen option does, under the choice
    expect(screen.getByText(/pushes the task's branch and opens a pull request/)).toBeInTheDocument();
  });

  it("finishing select hidden at done", async () => {
    setup(wf({ stage: "done", status: "running" }));
    await screen.findByText(/Running: Done/);
    expect(screen.queryByLabelText("Finishing option")).not.toBeInTheDocument();
    expect(screen.getByText("Push and open a pull request")).toBeInTheDocument();
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

  it("offers the stage checklist on an unassigned task the viewer may set up", async () => {
    const fetchMock = setup(wf({ can_set_manual: true }), {
      agent: null,
      post: new Response(JSON.stringify(wf({ driver: "manual" })), { status: 200 }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Use stage checklist" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/tasks/PAY-1/workflow",
        expect.objectContaining({ method: "PATCH", body: JSON.stringify({ driver: "manual", stage: "brainstorm" }) }),
      ),
    );
  });

  it("hides the checklist from someone who may not set it up", async () => {
    setup(wf({ can_set_manual: false }), { agent: null });
    await screen.findByText("Not started");
    expect(screen.queryByRole("button", { name: "Use stage checklist" })).not.toBeInTheDocument();
  });

  it("never shows the checklist on an agent task, even while agents are loading", async () => {
    setup(wf({ can_set_manual: true }), { agent: null, unassigned: false });
    await screen.findByText("Not started");
    expect(screen.queryByRole("button", { name: "Use stage checklist" })).not.toBeInTheDocument();
  });

  it("does not show the checklist while a connect_only workflow is running", async () => {
    setup(wf({ driver: "connect_only", status: "running", enforcement: "unenforced", can_set_manual: true }), { agent: null });
    await screen.findByText(/Running/);
    expect(screen.queryByRole("button", { name: "Use stage checklist" })).not.toBeInTheDocument();
    expect(screen.getByText(/Not enforced/)).toBeInTheDocument();
  });

  it("offers Pause on an active connect_only workflow to those who may act on it", async () => {
    const fetchMock = setup(wf({ driver: "connect_only", status: "waiting_human", needs: "design_approval", enforcement: "unenforced" }), { agent: null });
    fireEvent.click(await screen.findByRole("button", { name: "Pause" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/tasks/PAY-1/workflow/pause"), expect.objectContaining({ method: "POST" })),
    );
  });

  it("hides Pause on a connect_only workflow from others and once paused", async () => {
    setup(wf({ driver: "connect_only", status: "running", enforcement: "unenforced", can_act: false }), { agent: null });
    await screen.findByText(/Running/);
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
    cleanup();
    setup(wf({ driver: "connect_only", status: "paused", enforcement: "unenforced" }), { agent: null });
    await screen.findByText("Paused");
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
  });

  it("marks the current checklist stage in text", async () => {
    setup(wf({ driver: "manual", stage: "plan", can_set_manual: true }), { agent: null });
    expect(await screen.findByRole("button", { name: "Plan (current)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Build" })).toBeInTheDocument();
  });

  it("shows Start for a manual-idle task that later got an agent", async () => {
    setup(wf({ driver: "manual", status: "idle" }));
    expect(await screen.findByRole("button", { name: "Start" })).toBeInTheDocument();
  });

  it("does not offer Start for a manual workflow that is under way", async () => {
    setup(wf({ driver: "manual", status: "paused" }));
    await screen.findByText("Paused");
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
  });

  it("hides the finishing select while idle", async () => {
    setup(wf());
    await screen.findByRole("button", { name: "Start" });
    expect(screen.queryByLabelText("Finishing option")).not.toBeInTheDocument();
    expect(screen.getByText("Push and open a pull request")).toBeInTheDocument();
  });

  it("explains a forced finishing option instead of offering a select", async () => {
    setup(wf({ stage: "build", status: "running", finishing_forced: true }));
    expect(await screen.findByText(/required by the project's human code review setting/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Finishing option")).not.toBeInTheDocument();
  });

  it("uses past tense once finished and hides the enforcement line when idle with no agent", async () => {
    setup(wf({ stage: "done", status: "finished", branch: "task/pay-1" }));
    expect(await screen.findByText(/Finished with:/)).toBeInTheDocument();
    cleanup();
    setup(wf(), { agent: null });
    await screen.findByText("Not started");
    expect(screen.queryByText(/Rules enforced/)).not.toBeInTheDocument();
  });

  it("does not claim the viewer must act when the view is read-only", async () => {
    setup(wf({ stage: "plan", status: "waiting_human", needs: "plan_approval", can_act: true }), { disabled: true });
    await screen.findByText("Waiting: Approve the plan");
    expect(screen.queryByText(/for you/i)).not.toBeInTheDocument();
  });

  it("refetches the workflow after a 409 from an action", async () => {
    const fetchMock = setup(wf(), { post: new Response(JSON.stringify({ detail: "workflow_active" }), { status: 409 }) });
    const loads = () => fetchMock.mock.calls.filter(([u, i]) => String(u).endsWith("/workflow") && !i?.method).length;
    fireEvent.click(await screen.findByRole("button", { name: "Start" }));
    await screen.findByRole("alert");
    await waitFor(() => expect(loads()).toBeGreaterThan(1));
  });

  it("shows the role and step on run rows", async () => {
    setup(wf({ stage: "build", status: "running" }), {
      runs: [{ id: "r1", status: "completed", policy: "workspace", workflow_role: "implement", step: 2, summary: "done it", reason: null }],
    });
    expect(await screen.findByText(/step 2 · implement · completed · workspace · done it/)).toBeInTheDocument();
  });

  it("shows an error message when an action fails", async () => {
    setup(wf(), { post: new Response(JSON.stringify({ detail: "cannot_use_agent" }), { status: 403 }) });
    fireEvent.click(await screen.findByRole("button", { name: "Start" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You can only use your own agents");
  });
});

describe("WorkflowPanel branches", () => {
  const pr = (url: string) => ({ url, state: "open", checks: "none", review: "none", tracked: true });

  it("says where the work starts and is delivered, with both pull requests", async () => {
    setup(wf({
      status: "waiting_human", stage: "done", needs: "human_code_review", branch: "megoo/PAY-1-fix", pr_url: "https://g/pr/7",
      start_branch: "main", back_merge_into: "develop", branch_from: "main",
      pull_request: pr("https://g/pr/7"), back_merge_branch: "megoo/PAY-1-fix-to-develop", back_merge_pr_url: "https://g/pr/8",
      back_merge_pull_request: pr("https://g/pr/8"), finish_outcome: "pr_opened",
    } as Partial<Workflow>));
    expect(await screen.findByText("Starts from main. Delivers to main, then develop.")).toBeInTheDocument();
    expect(screen.getByText("Into develop:")).toBeInTheDocument();
    const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(links).toEqual(expect.arrayContaining(["https://g/pr/7", "https://g/pr/8"]));
  });

  it("shows the back-merge branch even without a pull request (plain git)", async () => {
    setup(wf({
      status: "finished", stage: "done", branch: "megoo/PAY-1-fix", start_branch: "main", back_merge_into: "develop",
      back_merge_branch: "megoo/PAY-1-fix-to-develop", finish_outcome: "branch_pushed",
    } as Partial<Workflow>));
    expect(await screen.findByText("megoo/PAY-1-fix-to-develop")).toBeInTheDocument();
    expect(screen.getByText("Into develop:")).toBeInTheDocument();
  });

  it("before work starts, says where it will start", async () => {
    setup(wf({ branch_from: null } as Partial<Workflow>));
    expect(await screen.findByText("Will start from the default branch.")).toBeInTheDocument();
  });

  it("reminds that a kept production fix still has to reach both branches", async () => {
    setup(wf({
      status: "finished", stage: "done", branch: "megoo/PAY-1-fix", finishing_option: "keep_branch",
      start_branch: "main", back_merge_into: "develop", finish_outcome: "branch_kept",
    } as Partial<Workflow>));
    expect(await screen.findByText("This fix still has to reach main and develop.")).toBeInTheDocument();
  });
});

describe("WorkflowPanel: sent back by a review on the pull request", () => {
  const fixing = () =>
    wf({
      stage: "build", status: "running", pr_url: "https://github.com/acme/pay/pull/42", branch: "megoo/PAY-1-retries",
      pr_fix_rounds: 2, pr_fix_trigger: { kind: "review", by: "rev", pr_number: 42, excerpt: "Two things", round: 2 },
    } as Partial<Workflow>);

  it("says who asked, who is fixing and the round, and Don't send back stops it", async () => {
    const fixRun = { id: "r1", status: "running", workflow_role: "pr_fix", policy: "workspace", step: null };
    const fetchMock = setup(fixing(), { post: new Response(JSON.stringify(fixing()), { status: 200 }), runs: [fixRun] });
    expect(await screen.findByText("Changes requested on PR #42 by rev · Ann's Codex is fixing them · round 2 of 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Don't send back" }));
    const confirm = await screen.findByRole("alertdialog");
    fireEvent.click(within(confirm).getByRole("button", { name: "Don't send back" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u, i]) => String(u) === "/api/tasks/PAY-1/workflow/send-back/cancel" && i?.method === "POST")).toBe(true),
    );
  });

  it("follows the fix run itself: a retried fix shows, a stale request on another run doesn't", async () => {
    const trigger = { kind: "fix_comment", by: "mo", pr_number: 42, excerpt: "/fix it", round: 3 };
    const fixRun = { id: "r1", status: "running", workflow_role: "pr_fix", policy: "workspace", step: null };
    setup(wf({ stage: "done", status: "running", pr_fix_rounds: 3, pr_fix_trigger: trigger } as Partial<Workflow>), { runs: [fixRun] });
    expect(await screen.findByText(/by mo · Ann's Codex is fixing them · round 3 of 3/)).toBeInTheDocument();
    cleanup();
    const buildRun = { id: "r2", status: "running", workflow_role: "implement", policy: "workspace", step: 1 };
    setup(wf({ stage: "build", status: "running", pr_fix_rounds: 3, pr_fix_trigger: trigger } as Partial<Workflow>), { runs: [buildRun] });
    await screen.findAllByText(/Build/);
    expect(screen.queryByRole("button", { name: "Don't send back" })).toBeNull();
  });

  it("shows nothing of the kind outside a fix round", async () => {
    setup(wf({ status: "running", stage: "build" }));
    await screen.findAllByText(/Build/);
    expect(screen.queryByRole("button", { name: "Don't send back" })).toBeNull();
  });
});

describe("WorkflowPanel: an agent reviewing the pull request", () => {
  it("names the reviewer and the pull request while its review run goes", async () => {
    const run = { id: "r9", status: "running", workflow_role: "pr_review", policy: "read_only", step: null,
      agent: { id: "a9", name: "review-bot" } };
    setup(wf({ stage: "done", status: "running", pr_url: "https://github.com/acme/pay/pull/42", branch: "megoo/PAY-1-x" }), { runs: [run] });
    expect(await screen.findByText("review-bot is reviewing PR #42")).toBeInTheDocument();
  });
});

describe("WorkflowPanel agent merge confirmation", () => {
  const pr = (extra: Record<string, unknown> = {}) => ({
    url: "https://github.com/o/r/pull/7", state: "open", checks: "none", review: "none", tracked: true, host: "github", ...extra,
  });
  const base = { stage: "done", status: "waiting_human", branch: "megoo/PAY-1-fix", pr_url: "https://github.com/o/r/pull/7" } as const;

  it("says the agent merged and offers a quiet Mark merged", async () => {
    const fetchMock = setup(wf({ ...base, needs: "merge_confirmation", pull_request: pr() } as Partial<Workflow>));
    expect(
      await screen.findByText("The agent merged the pull request. MegooColab finishes the round when GitHub shows the merge."),
    ).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Mark merged" });
    expect(button.className).not.toContain("bg-cyan");
    fireEvent.click(button);
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/workflow/human-review") && i?.method === "POST");
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ approved: true });
    });
  });

  it("falls back to the git host when the host is unknown", async () => {
    setup(wf({ ...base, needs: "merge_confirmation", pull_request: pr({ host: null }) } as Partial<Workflow>));
    expect(await screen.findByText(/finishes the round when the git host shows the merge\./)).toBeInTheDocument();
  });

  it("an unconfirmed merge shows the reason and a Mark merged way out", async () => {
    const fetchMock = setup(wf({
      ...base, needs: "escalation", escalation_reason: "merge_not_confirmed", pull_request: pr({ error: "forbidden" }),
    } as Partial<Workflow>));
    expect(await screen.findByText("The agent merged the pull request, but MegooColab couldn't confirm it.")).toBeInTheDocument();
    // once: in the escalation, not again under the pull request
    expect(screen.getAllByText(/GitHub refused the token \(forbidden\)/)).toHaveLength(1);
    expect(screen.queryByText(/MegooColab can't read this pull request/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Mark merged" }));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/workflow/escalation") && i?.method === "POST");
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ action: "accept" });
    });
  });

  it("an unconfirmed merge that GitHub still shows open says so", async () => {
    setup(wf({
      ...base, needs: "escalation", escalation_reason: "merge_not_confirmed", pull_request: pr({ error: null, state: "open" }),
    } as Partial<Workflow>));
    expect(await screen.findByText("GitHub still shows it open.")).toBeInTheDocument();
  });

  it("an unconfirmed merge MegooColab no longer follows says so, whatever its last read said", async () => {
    setup(wf({
      ...base, needs: "escalation", escalation_reason: "merge_not_confirmed",
      pull_request: pr({ tracked: false, host: null, error: "forbidden" }),
    } as Partial<Workflow>));
    expect(
      await screen.findByText("MegooColab no longer follows this pull request (its git connection was removed)."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/refused the token/)).toBeNull();
  });

  it("says nothing of reads for a pull request MegooColab doesn't follow", async () => {
    setup(wf({
      ...base, needs: "human_code_review", pull_request: pr({ tracked: false, host: null, error: "forbidden", limited: "checks" }),
    } as Partial<Workflow>));
    expect(await screen.findByRole("button", { name: "Mark merged" })).toBeInTheDocument();
    expect(screen.queryByText(/MegooColab can't read this pull request/)).toBeNull();
    expect(screen.queryByText(/Checks unknown/)).toBeNull();
  });

  it("says under the pull request when it can't be read, and when it tries again", async () => {
    const at = "2026-11-05T14:30:00Z";
    setup(wf({ ...base, needs: "human_code_review", pull_request: pr({ error: "unreachable", next_check_at: at }) } as Partial<Workflow>));
    const time = new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    expect(
      await screen.findByText(`MegooColab can't read this pull request: GitHub couldn't be reached. It tries again at ${time}.`),
    ).toBeInTheDocument();
  });

  it("says what a partial read couldn't see", async () => {
    setup(wf({ ...base, needs: "human_code_review", pull_request: pr({ limited: "checks" }) } as Partial<Workflow>));
    expect(await screen.findByText("Checks unknown: the token can't read commit statuses or checks.")).toBeInTheDocument();
  });
});
