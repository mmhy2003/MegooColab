import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type BrowserContext } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { delivery, pullRequestDelivery, startFakeGit, type FakeGit } from "./helpers/fakeGit";
import { buildBinaries, mcp, onPrompt, mintLinkedRunnerToken, startRunner, type RunnerHandle } from "./helpers/runner";

/**
 * End-to-end test of the git integration: a self-hosted GitHub connection (a fake GitHub Enterprise on the host),
 * a repository picked from its list with its own webhook made by Create it for me, the pull request the agent's
 * Finish run opens followed; a webhook signed with the repository's secret about the merge finishes the task, a
 * forged one is refused, and a closed pull request escalates. Needs the Go toolchain and git on the PATH, and a fresh
 * stack (see README "Git and notifications end-to-end tests"). Project key GIT.
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;
const TOKEN = "ghp_e2eFakeReadOnlyToken";
const FIRST = "GIT-1"; // its plan's one step becomes GIT-2
const SECOND = "GIT-3";
const THIRD = "GIT-5"; // GIT-3's plan step is GIT-4

// what each run's prompt starts with (backend/app/workflow/methodology_texts/defaults)
const BRAINSTORM = "# Brainstorm: turn the task into an approved design";
const PLAN = "# Plan: break the approved design into steps";
const IMPLEMENT = "# Build: implement one plan step";
const STEP_REVIEW = "# Build: review one implemented step";
const FINAL_REVIEW = "# Review: final review of the whole change";
const FINISH = "# Finish: verify and integrate the finished work";
const PR_FIX = "# Fix: address the changes requested on the pull request";
const PR_REVIEW = "# Review: the pull request on the host";

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
    // a review on the pull request sent the task back: fix, commit (the push has nowhere to go here), report
    onPrompt(
      PR_FIX,
      { write: { path: `${key}-fix.txt`, content: "backed off\n" } },
      { commit: { message: `${key}: back off between retries`, all: true } },
      mcp("report_pr_fix", { key, summary: "Added a back-off", tests_passed: true }),
    ),
    // the project's agent reviews the pull request: changes first, then it approves and merges
    onPrompt(
      PR_REVIEW,
      onPrompt("review round 1", mcp("submit_pr_review", {
        key, verdict: "changes_requested", summary: "Retry needs a back-off",
        findings: [{ severity: "important", file: `${key}.txt`, line: 1, summary: "No back-off" }],
      })),
      onPrompt("review round 2", mcp("submit_pr_review", { key, verdict: "approved", summary: "Looks good", merged: true })),
    ),
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

  // 1. Admin → Git: a self-hosted GitHub connection, its address and a token, no webhook secret; Test shows the login
  await page.goto("/admin/git");
  await page.getByRole("button", { name: "Add connection" }).click();
  await page.getByRole("group", { name: "Kind" }).getByRole("button", { name: "GitHub" }).click();
  await page.getByRole("group", { name: "Where" }).getByRole("button", { name: "Self-hosted" }).click();
  await page.getByLabel("Server address").fill(fake.baseUrl);
  await page.getByLabel("Name").fill("Fake GHE");
  await page.getByLabel("Access token").fill(TOKEN);
  await page.getByRole("button", { name: "Save" }).click();
  const row = page.getByRole("listitem").filter({ hasText: "Fake GHE" });
  await expect(row).toBeVisible();
  await expect(page.getByText(TOKEN)).toHaveCount(0);
  await row.getByRole("button", { name: "Test" }).click();
  await expect(row.getByText("Connected as fake-bot")).toBeVisible({ timeout: 15_000 });
  type Conn = { id: string; name: string; token_set: boolean; hosted: boolean };
  const conn = (await get<Conn[]>(request, "/api/admin/git-connections")).find((c) => c.name === "Fake GHE")!;
  expect(conn.token_set).toBe(true);
  expect(conn.hosted).toBe(false);
  await expect(row.getByLabel("Webhook URL")).toHaveCount(0);

  // 2. project GIT requires a human code review; in Settings its repository is picked from the connection's list,
  // and Create it for me makes the repository's own webhook on the host
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Git Team", description: "" });
  await post(request, "/api/projects", { key: "GIT", name: "Git Demo", description: "", team_ids: [team.id] });
  const patched = await request.patch("/api/projects/GIT", {
    data: { sprints_enabled: false, pr_review: "human", send_back_on_changes_requested: true },
    headers: WEB,
  });
  expect(patched.ok()).toBeTruthy();
  await page.goto("/projects/GIT/settings");
  await page.getByRole("tab", { name: "Repositories" }).click();
  await page.getByLabel("Provider").selectOption({ label: "Fake GHE" });
  await page.getByLabel("Repository", { exact: true }).fill("r");
  await page.getByRole("list", { name: "Repositories" }).getByRole("button", { name: /o\/r/ }).click();
  await page.getByRole("button", { name: "Add", exact: true }).click();
  type RepoRow = { id: string; name: string; url: string; connection: { name: string } | null; webhook_status: string };
  await expect.poll(async () => (await get<RepoRow[]>(request, "/api/projects/GIT/repositories"))[0]?.connection?.name).toBe("Fake GHE");
  const linked = (await get<RepoRow[]>(request, "/api/projects/GIT/repositories"))[0];
  expect(linked).toMatchObject({ name: "o/r", url: `${fake.baseUrl}/o/r`, webhook_status: "not_set_up" });
  await page.getByRole("button", { name: "Set up webhook" }).click();
  const hookDialog = page.getByRole("dialog", { name: "Webhook for o/r" });
  await hookDialog.getByRole("button", { name: "Create it for me" }).click();
  await expect(hookDialog.getByText("Created on GitHub.")).toBeVisible({ timeout: 15_000 });
  const hookUrl = `/api/git/webhooks/repos/${linked.id}`;
  expect(fake.hooks.size).toBe(1);
  const [made] = [...fake.hooks.values()];
  expect(made.url.endsWith(hookUrl), made.url).toBe(true);
  // a delivery signed with the repository's own secret: the webhook reads as working
  const ping = pullRequestDelivery(99, made.secret);
  expect((await request.post(hookUrl, { data: ping.body, headers: ping.headers })).status()).toBe(204);
  await expect(hookDialog.getByText(/^Webhook working/)).toBeVisible({ timeout: 15_000 });
  await hookDialog.getByRole("button", { name: "Done" }).click();
  await expect(page.getByText(/^Webhook working/)).toBeVisible();

  // the admin's agent, bound to GIT alone, and the runner with both tasks' scenarios
  type Agent = { id: string; name: string };
  const mine = await get<Agent[]>(request, "/api/agents/mine");
  const agent = mine.find((a) => a.name === AGENT_NAME) ?? (await post<Agent>(request, "/api/agents", { program: "claude_code" }));
  const bound = await request.put(`/api/agents/${agent.id}/bindings`, {
    data: { bindings: [{ project_ref: "GIT", local_path: repo }] },
    headers: WEB,
  });
  expect(bound.ok(), await bound.text()).toBeTruthy();
  const runnerToken = await mintLinkedRunnerToken(request, agent.id, "Git runner");
  leftovers.runner = startRunner({
    url: BASE,
    token: runnerToken,
    home: join(work, "home"),
    adapterOverride: bins.fakeAgent,
    scenario: [workflowFor(FIRST, prUrl(1)), workflowFor(SECOND, prUrl(2)), workflowFor(THIRD, prUrl(3))],
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

  // the task's Activity follows the pull request: the agent's push and pull request (the finish run has just ended),
  // and a person's review asking for changes
  const send = async (event: string, payload: object) => {
    const d = delivery(event, payload, made.secret);
    expect((await request.post(hookUrl, { data: d.body, headers: d.headers })).status()).toBe(204);
  };
  const pr1 = { number: 1, html_url: prUrl(1), title: "Ship the feature", head: { ref: "megoo/GIT-1" }, base: { ref: "main" } };
  await send("push", { ref: "refs/heads/megoo/GIT-1", after: "1".repeat(40), pusher: { name: "admin-gh" },
    commits: [{ message: "GIT-1: do it" }] });
  await send("pull_request", { action: "opened", number: 1, pull_request: pr1, sender: { login: "admin-gh" } });
  await send("pull_request_review", { action: "submitted", pull_request: pr1, sender: { login: "rev" },
    review: { id: 5, state: "changes_requested", body: "Add a back-off", html_url: `${prUrl(1)}#review-5`,
      author_association: "COLLABORATOR" } });
  const activity = (text: string) => drawer.getByRole("listitem").filter({ hasText: text });
  await expect(activity("pushed 1 commit to megoo/GIT-1")).toBeVisible({ timeout: 15_000 });
  await expect(activity("pushed 1 commit to megoo/GIT-1")).toContainText(AGENT_NAME);
  await expect(activity("pushed 1 commit to megoo/GIT-1").getByText("agent", { exact: true })).toBeVisible();
  await expect(activity("opened PR #1 · megoo/GIT-1 → main")).toContainText(AGENT_NAME);
  await expect(activity("requested changes on PR #1")).toContainText("rev");
  await expect(activity("requested changes on PR #1")).toContainText("Add a back-off");
  // the project sends the task back on changes requested: the agent fixes it, and the task waits for the merge again
  await expect(activity("Sent back to its agent: changes requested on PR #1 by rev (round 1 of 3)")).toBeVisible({ timeout: 15_000 });
  await expect(activity("Fixed and pushed to PR #1 (round 1 of 3)")).toBeVisible({ timeout: 60_000 });
  await expect(activity("Fixed and pushed to PR #1 (round 1 of 3)")).toContainText("Added a back-off");
  await expect(panel.getByRole("button", { name: "Mark merged" })).toBeVisible({ timeout: 15_000 });
  expect((await get<Workflow>(request, `/api/tasks/${FIRST}/workflow`)).needs).toBe("human_code_review");

  // 4. someone merges it on the git host; the signed webhook makes MegooColab look, and the task is done
  fake.prs.set(1, { state: "closed", merged: true, checks: "success", reviews: [{ state: "APPROVED", login: "rev" }] });
  const merge = pullRequestDelivery(1, made.secret, prUrl(1));
  const hook = await request.post(hookUrl, { data: merge.body, headers: merge.headers });
  expect(hook.status()).toBe(204);
  await expect(panel.getByRole("link", { name: "PR merged" })).toBeVisible({ timeout: 30_000 });
  await expect(panel.getByText("Finished", { exact: true })).toBeVisible({ timeout: 30_000 });
  expect((await get<Workflow>(request, `/api/tasks/${FIRST}/workflow`)).status).toBe("finished");
  await expect(drawer.getByText("Moved to Done by the workflow")).toBeVisible();
  // one line for the merge, naming who did it
  await expect(activity("mo merged PR #1")).toHaveCount(1);
  await expect(drawer.getByText("PR #1 merged")).toHaveCount(0);
  // and it all fits a phone
  await page.setViewportSize({ width: 280, height: 800 });
  await expect(activity("mo merged PR #1")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
  await page.setViewportSize({ width: 1280, height: 720 });

  // 5. a delivery with a wrong signature, or none, is refused and changes nothing
  const forged = pullRequestDelivery(1, "not-the-secret");
  expect((await request.post(hookUrl, { data: forged.body, headers: forged.headers })).status()).toBe(401);
  const unsigned = await request.post(hookUrl, {
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

  // 7. the project's pull requests are reviewed by an agent: GIT-5's agent reviews PR #3, asks for changes (the task goes
  // back to its agent, which fixes it), then approves and merges; MegooColab sees the merge and the task is done
  await page.keyboard.press("Escape");
  const agentReview = await request.patch("/api/projects/GIT", { data: { pr_review: "agent" }, headers: WEB });
  expect(agentReview.ok(), await agentReview.text()).toBeTruthy();
  fake.prs.set(3, { state: "open", merged: false, checks: "success", reviews: [] });
  await post(request, "/api/projects/GIT/tasks", { title: "Reviewed by an agent", type: "task", assignee_agent_id: agent.id });
  await post(request, `/api/tasks/${THIRD}/workflow/start`, {});
  await approve(request, THIRD, "design");
  await approve(request, THIRD, "plan");
  await page.goto(`/projects/GIT/board?task=${THIRD}`);
  const third = page.getByRole("dialog", { name: THIRD });
  const thirdActivity = (text: string) => third.getByRole("listitem").filter({ hasText: text });
  await expect(thirdActivity("requested changes on PR #3 · 1 finding")).toBeVisible({ timeout: 120_000 });
  await expect(thirdActivity("requested changes on PR #3 · 1 finding")).toContainText(AGENT_NAME);
  await expect(thirdActivity("Sent back to its agent: changes requested on PR #3")).toBeVisible({ timeout: 15_000 });
  await expect(thirdActivity("Fixed and pushed to PR #3 (round 1 of 3)")).toBeVisible({ timeout: 60_000 });
  await expect(thirdActivity("approved PR #3 and merged it")).toBeVisible({ timeout: 60_000 });
  // the agent merged it on the host; the host's webhook tells MegooColab
  fake.prs.set(3, { state: "closed", merged: true, checks: "success", reviews: [] });
  const merged3 = delivery("pull_request", {
    action: "closed", number: 3, sender: { login: "admin-gh" },
    pull_request: { number: 3, html_url: prUrl(3), merged: true, head: { ref: `megoo/${THIRD}` }, base: { ref: "main" } },
  }, made.secret);
  expect((await request.post(hookUrl, { data: merged3.body, headers: merged3.headers })).status()).toBe(204);
  await expect
    .poll(async () => (await get<Workflow>(request, `/api/tasks/${THIRD}/workflow`)).status, { timeout: 30_000 })
    .toBe("finished");
});
