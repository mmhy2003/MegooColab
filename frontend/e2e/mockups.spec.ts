import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type BrowserContext } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { buildBinaries, mcp, onPrompt, mintLinkedRunnerToken, startRunner, type RunnerHandle } from "./helpers/runner";

/**
 * End-to-end test of Plan 8: the agent shows two mockup versions while it brainstorms and the open task follows
 * them live; approving the version the design was submitted with approves the design; the implementer's decision
 * and recorded test run show on the task. Needs the Go toolchain and git on the PATH, and a fresh stack (see
 * README "Live mockups end-to-end test"). Project key MCK.
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;
const KEY = "MCK-1";
const BRAINSTORM = "# Brainstorm: turn the task into an approved design";
const PLAN = "# Plan: break the approved design into steps";
const IMPLEMENT = "# Build: implement one plan step";
const STEP_REVIEW = "# Build: review one implemented step";
const mockupHtml = (title: string) => `<html><body><h1>${title}</h1></body></html>`;

const SCENARIO = onPrompt(
  `## Task ${KEY}\n`,
  onPrompt(
    BRAINSTORM,
    mcp("show_mockup", { key: KEY, html: mockupHtml("Layout A"), title: "Layout A" }),
    { sleep_ms: 4000 },
    mcp("show_mockup", { key: KEY, html: mockupHtml("Layout B"), title: "Layout B" }),
    { sleep_ms: 3000 },
    mcp("submit_design", { key: KEY, markdown: "# Settings page\n\nLayout B: one column." }),
  ),
  onPrompt(PLAN, mcp("submit_plan", { key: KEY, markdown: "# Plan", steps: [{ title: "Build the page", detail: "One file." }] })),
  onPrompt(
    IMPLEMENT,
    { write: { path: "settings.txt", content: "one column\n" } },
    { commit: { message: "feat: settings page", all: true } },
    mcp("record_decision", {
      key: KEY,
      decision: "Kept one column on wide screens",
      reason: "Layout B was approved",
      cost_if_wrong: "A small CSS change",
      plan_said: "Build the page",
    }),
    mcp("record_tests", { key: KEY, command: "npm test", passed: true, total: 3, failed: 0 }),
    mcp("complete_step", { key: KEY, step: 1, summary: "Built the page", tests_passed: true, test_command: "npm test" }),
  ),
  onPrompt(STEP_REVIEW, mcp("submit_review", { key: KEY, verdict: "approved", findings: [] })),
);

type Workflow = { status: string; needs: string | null; stage: string };

async function post<T = unknown>(request: APIRequestContext, url: string, data: unknown): Promise<T> {
  const r = await request.post(url, { data, headers: WEB });
  expect(r.ok(), `${url}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return (await r.json().catch(() => null)) as T;
}

async function get<T = unknown>(request: APIRequestContext, url: string): Promise<T> {
  const r = await request.get(url);
  expect(r.ok(), `${url}: ${r.status()}`).toBeTruthy();
  return (await r.json()) as T;
}

function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", ["-c", "user.name=E2E", "-c", "user.email=e2e@acme.io", ...args], { cwd, stdio: "pipe" })
    .toString()
    .trim();
}

const leftovers: { runner?: RunnerHandle; ctx?: BrowserContext; work?: string } = {};

test.afterEach(async () => {
  const { runner, ctx, work } = leftovers;
  delete leftovers.runner;
  delete leftovers.ctx;
  delete leftovers.work;
  await runner?.stop();
  if (process.env.E2E_RUNNER_LOG) console.log(runner?.output());
  await ctx?.close();
  if (work) rmSync(work, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
});

test("live mockups, decisions and test runs reach the task", async ({ browser }) => {
  test.setTimeout(240_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-mockups-"));
  leftovers.work = work;
  const ctx = await browser.newContext();
  leftovers.ctx = ctx;
  const ui = await ctx.newPage();
  await setupOrSignIn(ui);
  const request = ui.request;

  // project MCK, the admin's agent bound to a fresh repository, and the runner with the scenario
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Mockup Team", description: "" });
  await post(request, "/api/projects", { key: "MCK", name: "Mockup Demo", description: "", team_ids: [team.id] });
  expect((await request.patch("/api/projects/MCK", { data: { sprints_enabled: false }, headers: WEB })).ok()).toBeTruthy();
  const bins = buildBinaries(join(work, "bin"));
  const repo = join(work, "repo");
  mkdirSync(repo);
  git(repo, "init", "-q");
  writeFileSync(join(repo, "README.md"), "# settings\n");
  git(repo, "add", ".");
  git(repo, "commit", "-q", "-m", "init");
  type Agent = { id: string; name: string; status: string };
  const mine = await get<Agent[]>(request, "/api/agents/mine");
  const agent = mine.find((a) => a.name === AGENT_NAME) ?? (await post<Agent>(request, "/api/agents", { program: "claude_code" }));
  const bound = await request.put(`/api/agents/${agent.id}/bindings`, {
    data: { bindings: [{ project_ref: "MCK", local_path: repo }] },
    headers: WEB,
  });
  expect(bound.ok(), await bound.text()).toBeTruthy();
  const token = await mintLinkedRunnerToken(request, agent.id, "Mockups");
  leftovers.runner = startRunner({
    url: BASE,
    token,
    home: join(work, "home"),
    adapterOverride: bins.fakeAgent,
    scenario: [SCENARIO],
    runnerBin: bins.runner,
  });
  await expect
    .poll(async () => (await get<Agent[]>(request, "/api/agents/mine")).find((a) => a.id === agent.id)?.status, { timeout: 20_000 })
    .toBe("online");

  // 1. the task is open while the agent brainstorms: v1 appears, then v2 replaces it with no reload
  await post(request, "/api/projects/MCK/tasks", { title: "Settings page", type: "task", assignee_agent_id: agent.id });
  await ui.goto(`/projects/MCK/board?task=${KEY}`);
  const drawer = ui.getByRole("dialog", { name: KEY });
  await post(request, `/api/tasks/${KEY}/workflow/start`, {});
  const mockups = drawer.locator("#mockups");
  await expect(mockups.getByTitle("Mockup v1: Layout A")).toBeVisible({ timeout: 60_000 });
  await expect(mockups.getByTitle("Mockup v2: Layout B")).toBeVisible({ timeout: 30_000 });
  await expect(mockups.getByText("v2 of 2")).toBeVisible();

  // 2. once the design waits, approving v2 (the version it was submitted with) approves the design
  await expect
    .poll(async () => (await get<Workflow>(request, `/api/tasks/${KEY}/workflow`)).needs, { timeout: 60_000 })
    .toBe("design_approval");
  await mockups.getByRole("button", { name: "Approve this version" }).click();
  await expect.poll(async () => (await get<Workflow>(request, `/api/tasks/${KEY}/workflow`)).stage, { timeout: 15_000 }).toBe("plan");
  type Doc = { kind: string; status: string; mockup_id: string | null };
  const [design] = (await get<Doc[]>(request, `/api/tasks/${KEY}/documents`)).filter((d) => d.kind === "design");
  const [, v2] = await get<{ id: string }[]>(request, `/api/tasks/${KEY}/mockups`);
  expect(design).toMatchObject({ status: "approved", mockup_id: v2.id });

  // 3. the plan is approved; the implementer records a decision and a test run, both shown on the task
  await expect
    .poll(async () => (await get<Workflow>(request, `/api/tasks/${KEY}/workflow`)).needs, { timeout: 60_000 })
    .toBe("plan_approval");
  await post(request, `/api/tasks/${KEY}/documents/plan/1/decision`, { approve: true });
  const decisions = drawer.locator("#decisions");
  await expect(decisions.getByText("Kept one column on wide screens")).toBeVisible({ timeout: 60_000 });
  await expect(decisions.getByText("Layout B was approved")).toBeVisible();
  await expect(drawer.locator("#document-plan").getByText("✓ 3 passed — npm test")).toBeVisible({ timeout: 15_000 });
});
