import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type BrowserContext } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { pullRequestDelivery, startFakeGit, type FakeGit } from "./helpers/fakeGit";
import { buildBinaries, mcp, onPrompt, startRunner, type RunnerHandle } from "./helpers/runner";

/**
 * End-to-end test of Plan 7's git integration: a GitHub Enterprise connection (a fake one on the host) follows
 * the pull request the agent's Finish run opens; a signed webhook about the merge finishes the task, a forged
 * one is refused, and a closed pull request escalates. Needs the Go toolchain and git on the PATH, and a fresh
 * stack (see README "Git and notifications end-to-end tests"). Project key GIT.
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;
const TOKEN = "ghp_e2eFakeReadOnlyToken";
const SECRET = "e2e-webhook-secret";
const FIRST = "GIT-1"; // its plan's one step becomes GIT-2
const SECOND = "GIT-3";

// what each run's prompt starts with (backend/app/workflow/methodology_texts/defaults)
const BRAINSTORM = "# Brainstorm: turn the task into an approved design";
const PLAN = "# Plan: break the approved design into steps";
const IMPLEMENT = "# Build: implement one plan step";
const STEP_REVIEW = "# Build: review one implemented step";
const FINAL_REVIEW = "# Review: final review of the whole change";
const FINISH = "# Finish: verify and integrate the finished work";

/** The whole workflow for one task, finishing with a pull request at `prUrl`. */
function workflowFor(key: string, prUrl: string) {
  return onPrompt(
    `## Task ${key}\n`,
    onPrompt(BRAINSTORM, mcp("submit_design", { key, markdown: `# ${key} design\n\nDo the thing.` })),
    onPrompt(PLAN, mcp("submit_plan", { key, markdown: `# ${key} plan`, steps: [{ title: "Do it", detail: "One file." }] })),
    onPrompt(
      IMPLEMENT,
      { write: { path: `${key}.txt`, content: "done\n" } },
      { commit: { message: `${key}: do it`, all: true } },
      mcp("complete_step", { key, step: 1, summary: "Done", tests_passed: true }),
    ),
    onPrompt(STEP_REVIEW, mcp("submit_review", { key, verdict: "approved", findings: [] })),
    onPrompt(FINAL_REVIEW, mcp("submit_review", { key, verdict: "approved", findings: [] })),
    onPrompt(FINISH, mcp("report_finish", { key, outcome: "pr_opened", branch: `megoo/${key}`, pr_url: prUrl, tests_passed: true })),
  );
}

type Workflow = { status: string; needs: string | null; stage: string; escalation_reason: string | null };

async function post<T = unknown>(request: APIRequestContext, url: string, data: unknown): Promise<T> {
  const r = await request.post(url, { data, headers: WEB });
  expect(r.ok(), `${url}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return (await r.json()) as T;
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

/** Waits for the workflow to need `needs`, then approves the document version 1 of `kind` (design or plan). */
async function approve(request: APIRequestContext, key: string, kind: "design" | "plan") {
  await expect
    .poll(async () => (await get<Workflow>(request, `/api/tasks/${key}/workflow`)).needs, { timeout: 60_000 })
    .toBe(`${kind}_approval`);
  await post(request, `/api/tasks/${key}/documents/${kind}/1/decision`, { approve: true });
}

const leftovers: { runner?: RunnerHandle; ctx?: BrowserContext; work?: string; fake?: FakeGit } = {};

test.afterEach(async () => {
  const { runner, ctx, work, fake } = leftovers;
  delete leftovers.runner;
  delete leftovers.ctx;
  delete leftovers.work;
  delete leftovers.fake;
  await runner?.stop();
  if (process.env.E2E_RUNNER_LOG) console.log(runner?.output());
  await ctx?.close();
  await fake?.close();
  if (work) rmSync(work, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
});

test("a pull request followed through a git connection", async ({ browser }) => {
  test.setTimeout(360_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-git-"));
  leftovers.work = work;
  const fake = await startFakeGit(TOKEN);
  leftovers.fake = fake;
  const prUrl = (n: number) => `${fake.baseUrl}/o/r/pull/${n}`;
  const bins = buildBinaries(join(work, "bin"));
  const repo = join(work, "repo");
  mkdirSync(repo);
  git(repo, "init", "-q");
  writeFileSync(join(repo, "README.md"), "# r\n");
  git(repo, "add", ".");
  git(repo, "commit", "-q", "-m", "init");

  const ctx = await browser.newContext();
  leftovers.ctx = ctx;
  const page = await ctx.newPage();
  await setupOrSignIn(page);
  const request = page.request;

  // 1. Admin → Git: a GitHub Enterprise connection with a token and a webhook secret; Test shows the login
  await page.goto("/admin/git");
  await page.getByRole("button", { name: "Add connection" }).click();
  await page.getByLabel("Name").fill("Fake GHE");
  await page.getByLabel("Kind").selectOption("github");
  await page.getByLabel("Base URL").fill(fake.baseUrl);
  await page.getByLabel("Token").fill(TOKEN);
  await page.getByLabel("Webhook secret").fill(SECRET);
  await page.getByRole("button", { name: "Save" }).click();
  const row = page.getByRole("listitem").filter({ hasText: "Fake GHE" });
  await expect(row).toBeVisible();
  await expect(page.getByText(TOKEN)).toHaveCount(0);
  await row.getByRole("button", { name: "Test" }).click();
  await expect(row.getByText("Connected as fake-bot")).toBeVisible({ timeout: 15_000 });
  type Conn = { id: string; name: string; token_set: boolean };
  const conn = (await get<Conn[]>(request, "/api/admin/git-connections")).find((c) => c.name === "Fake GHE")!;
  expect(conn.token_set).toBe(true);
  await expect(row.getByLabel("Webhook URL")).toHaveValue(`${BASE}/api/git/webhooks/${conn.id}`);

  // 2. project GIT requires a human code review; its repository is linked to the connection in Settings
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Git Team", description: "" });
  await post(request, "/api/projects", { key: "GIT", name: "Git Demo", description: "", team_ids: [team.id] });
  const patched = await request.patch("/api/projects/GIT", {
    data: { sprints_enabled: false, require_human_code_review: true },
    headers: WEB,
  });
  expect(patched.ok()).toBeTruthy();
  await post(request, "/api/projects/GIT/repositories", { name: "r", url: `${fake.baseUrl}/o/r`, provider: "github" });
  await page.goto("/projects/GIT/settings");
  await page.getByRole("tab", { name: "Repositories" }).click();
  await page.getByLabel("Connection for r").selectOption({ label: "Fake GHE" });
  await expect
    .poll(async () => (await get<{ connection: { name: string } | null }[]>(request, "/api/projects/GIT/repositories"))[0].connection?.name)
    .toBe("Fake GHE");

  // the admin's agent, bound to GIT alone, and the runner with both tasks' scenarios
  type Agent = { id: string; name: string };
  const mine = await get<Agent[]>(request, "/api/agents/mine");
  const agent = mine.find((a) => a.name === AGENT_NAME) ?? (await post<Agent>(request, "/api/agents", { program: "claude_code" }));
  const bound = await request.put(`/api/agents/${agent.id}/bindings`, {
    data: { bindings: [{ project_ref: "GIT", local_path: repo }] },
    headers: WEB,
  });
  expect(bound.ok(), await bound.text()).toBeTruthy();
  const runnerToken = (await post<{ secret: string }>(request, "/api/tokens", { name: "Git runner", scopes: ["runner"] })).secret;
  leftovers.runner = startRunner({
    url: BASE,
    token: runnerToken,
    home: join(work, "home"),
    adapterOverride: bins.fakeAgent,
    scenario: [workflowFor(FIRST, prUrl(1)), workflowFor(SECOND, prUrl(2))],
    runnerBin: bins.runner,
  });
  await expect.poll(async () => (await get<{ id: string; status: string }[]>(request, "/api/agents/mine")).find((a) => a.id === agent.id)?.status, {
    timeout: 20_000,
  }).toBe("online");

  // 3. GIT-1 runs to Finish, which opens pull request #1: open, checks pending; the task waits for the merge
  fake.prs.set(1, { state: "open", merged: false, checks: "pending", reviews: [] });
  await post(request, "/api/projects/GIT/tasks", { title: "Ship the feature", type: "task", assignee_agent_id: agent.id });
  await post(request, `/api/tasks/${FIRST}/workflow/start`, {});
  await approve(request, FIRST, "design");
  await approve(request, FIRST, "plan");
  await expect
    .poll(async () => (await get<Workflow>(request, `/api/tasks/${FIRST}/workflow`)).needs, { timeout: 120_000 })
    .toBe("human_code_review");
  await page.goto(`/projects/GIT/board?task=${FIRST}`);
  const drawer = page.getByRole("dialog", { name: FIRST });
  const panel = drawer.getByRole("region", { name: "Workflow" });
  const badge = panel.getByRole("link", { name: "PR open · checks pending" });
  await expect(badge).toBeVisible({ timeout: 30_000 });
  await expect(badge).toHaveAttribute("href", prUrl(1));
  await expect(page.getByRole("region", { name: /column$/ }).getByRole("link", { name: "PR open · checks pending" })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Mark merged" })).toBeVisible();
  expect(fake.requests).toContain("/api/v3/repos/o/r/pulls/1");

  // 4. someone merges it on the git host; the signed webhook makes MegooColab look, and the task is done
  fake.prs.set(1, { state: "closed", merged: true, checks: "success", reviews: [{ state: "APPROVED", login: "rev" }] });
  const delivery = pullRequestDelivery(1, SECRET);
  const hook = await request.post(`/api/git/webhooks/${conn.id}`, { data: delivery.body, headers: delivery.headers });
  expect(hook.status()).toBe(204);
  await expect(panel.getByRole("link", { name: "PR merged" })).toBeVisible({ timeout: 30_000 });
  await expect(panel.getByText("Finished", { exact: true })).toBeVisible({ timeout: 30_000 });
  expect((await get<Workflow>(request, `/api/tasks/${FIRST}/workflow`)).status).toBe("finished");
  await expect(drawer.getByText("Moved to Done by the workflow")).toBeVisible();

  // 5. a delivery with a wrong signature, or none, is refused and changes nothing
  const forged = pullRequestDelivery(1, "not-the-secret");
  expect((await request.post(`/api/git/webhooks/${conn.id}`, { data: forged.body, headers: forged.headers })).status()).toBe(401);
  const unsigned = await request.post(`/api/git/webhooks/${conn.id}`, {
    data: forged.body,
    headers: { "content-type": "application/json" },
  });
  expect(unsigned.status()).toBe(401);

  // 6. GIT-3's pull request #2 is closed without a merge: the workflow escalates, and Accept finishes it
  await page.keyboard.press("Escape");
  fake.prs.set(2, { state: "closed", merged: false, checks: "failure", reviews: [] });
  await post(request, "/api/projects/GIT/tasks", { title: "An idea that was dropped", type: "task", assignee_agent_id: agent.id });
  await post(request, `/api/tasks/${SECOND}/workflow/start`, {});
  await approve(request, SECOND, "design");
  await approve(request, SECOND, "plan");
  await expect
    .poll(async () => (await get<Workflow>(request, `/api/tasks/${SECOND}/workflow`)).escalation_reason, { timeout: 120_000 })
    .toBe("pr_closed");
  await page.goto(`/projects/GIT/board?task=${SECOND}`);
  const second = page.getByRole("dialog", { name: SECOND }).getByRole("region", { name: "Workflow" });
  await expect(second.getByText("The pull request was closed without being merged.")).toBeVisible();
  await expect(second.getByRole("link", { name: "PR closed" })).toBeVisible();
  await second.getByRole("button", { name: "Accept" }).click();
  await expect(second.getByText("Finished", { exact: true })).toBeVisible({ timeout: 15_000 });
});
