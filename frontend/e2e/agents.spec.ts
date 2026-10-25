import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { buildBinaries, mcp, onPrompt, say, startRunner, type Binaries, type RunnerHandle } from "./helpers/runner";

/**
 * End-to-end test of Plan 2: UI -> server -> runner -> (fake) agent and back. Runs are workflow runs (Plan 3):
 * moving the card into In Progress starts the workflow, whose first run is a read-only brainstorm.
 * Needs the Go toolchain and git on the PATH; the runner runs on the host and
 * connects to the stack under test. See README "Agents end-to-end test".
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const SHOTS = process.env.E2E_SCREENSHOT_DIR; // optional: also capture review screenshots
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;

// the brainstorm run (read-only): it reports progress, tries to write, then asks a question
const SCENARIO = [
  onPrompt(
    "## Task AGT-1",
    say("Looking at the code"),
    { plan: [["Read the code", "completed"], ["Write notes", "in_progress"]] },
    { write: { path: "notes.txt", content: "tampered\n" } },
    say("Read-only done"),
    mcp("ask_human", {
      key: "AGT-1",
      question: "Which sync bug should I look at first?",
      choices: [
        { id: "orders", label: "Orders" },
        { id: "refunds", label: "Refunds" },
      ],
    }),
  ),
];

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.waitForTimeout(150);
    await page.screenshot({ path: join(SHOTS, `${name}-${scheme}.png`), fullPage: true });
  }
  await page.emulateMedia({ colorScheme: null });
}

// What the test leaves behind; torn down after it even when a step fails.
const leftovers: { runner?: RunnerHandle; ctx?: BrowserContext; work?: string } = {};

test.afterEach(async () => {
  const { runner, ctx, work } = leftovers;
  delete leftovers.runner;
  delete leftovers.ctx;
  delete leftovers.work;
  await runner?.stop();
  if (process.env.E2E_RUNNER_LOG) console.log(runner?.output());
  await ctx?.close();
  // the binaries, the repo and its worktree, and runner.json, which holds the token
  if (work) rmSync(work, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
});

function git(cwd: string, ...args: string[]) {
  execFileSync("git", ["-c", "user.name=E2E", "-c", "user.email=e2e@acme.io", ...args], { cwd, stdio: "pipe" });
}

test("agents end to end", async ({ browser, request }) => {
  test.setTimeout(240_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-agents-"));
  leftovers.work = work;
  const bins: Binaries = buildBinaries(join(work, "bin"));
  const repo = join(work, "repo");
  mkdirSync(repo);
  git(repo, "init", "-q");
  writeFileSync(join(repo, "README.md"), "# demo\n");
  git(repo, "add", ".");
  git(repo, "commit", "-q", "-m", "init");
  const home = join(work, "home");
  const launch = (token: string) => {
    leftovers.runner = startRunner({ url: BASE, token, home, adapterOverride: bins.fakeAgent, scenario: SCENARIO, runnerBin: bins.runner });
  };
  const stopRunner = async () => {
    await leftovers.runner?.stop();
  };

  const ctx = await browser.newContext();
  leftovers.ctx = ctx;
  const page = await ctx.newPage();
  // 1. setup, team "Agents Team", project AGT (sprints off)
  await setupOrSignIn(page);

  await page.goto("/teams");
  await page.getByRole("button", { name: "New team" }).click();
  await page.getByLabel("Name").fill("Agents Team");
  await page.getByRole("button", { name: "Create team" }).click();
  await expect(page.getByRole("heading", { name: "Agents Team" })).toBeVisible();
  await page.getByRole("button", { name: "Edit members" }).click();
  await page.getByLabel(ADMIN.name).check();
  await page.getByRole("button", { name: "Save members" }).click();

  await page.goto("/projects/new");
  await page.getByLabel("Name").fill("Agents Demo");
  await page.getByLabel(/^Key/).fill("AGT");
  await page.getByLabel("Agents Team").check();
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page).toHaveURL(/\/projects\/AGT\/board/);
  const patched = await page.request.patch("/api/projects/AGT", {
    data: { sprints_enabled: false },
    headers: { "X-Megoo-Client": "web" },
  });
  expect(patched.ok()).toBeTruthy();

  // 2. a token with the runner and mcp scopes
  await page.goto("/settings/tokens");
  await page.getByRole("button", { name: "New token" }).click();
  await page.getByLabel("Name").fill("Laptop runner");
  await page.getByLabel("Runner").check(); // MCP is on by default
  await page.getByRole("button", { name: "Create token" }).click();
  const token = await page.getByLabel("Your token").inputValue();
  expect(token).toMatch(/^mgc_/);
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByText("Laptop runner")).toBeVisible();
  await shot(page, "tokens");

  // 3. add the agent and bind it to AGT
  await page.goto("/settings/agents");
  await page.getByRole("button", { name: "Add agent" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Add agent" }).click();
  await expect(page.getByRole("heading", { name: AGENT_NAME })).toBeVisible();
  await page.getByRole("button", { name: "Add project" }).click();
  await page.getByLabel("Project").selectOption("AGT");
  await page.getByLabel("Local path").fill(repo);
  await page.getByRole("button", { name: "Save bindings" }).click();
  await expect(page.getByLabel("Local path")).toHaveValue(repo);
  await expect(page.getByText("Offline")).toBeVisible();

  // 4-5. start the runner; the agent is online within 5 s
  launch(token);
  await expect(page.getByText("Online")).toBeVisible({ timeout: 5_000 });
  await shot(page, "agents-settings");
  const agents = await (await page.request.get("/api/agents/mine")).json();
  const agentId: string = agents[0].id;
  const worktree = join(home, "cache", "megoocolab", "worktrees", agentId, "AGT-1");

  // 6. a task assigned to the agent; its workflow has not started
  await page.goto("/projects/AGT/board");
  await page.getByLabel("New task in To Do").fill("Investigate sync");
  await page.getByLabel("New task in To Do").press("Enter");
  await page.goto("/projects/AGT/board?task=AGT-1");
  const drawer = page.getByRole("dialog", { name: "AGT-1" });
  await expect(drawer).toBeVisible();
  await drawer.getByLabel("Assignee").selectOption({ label: AGENT_NAME });
  await expect(drawer.getByText(`assigned this to ${AGENT_NAME}`)).toBeVisible();
  const panel = drawer.getByRole("region", { name: "Workflow" });
  await expect(panel.getByText("Not started")).toBeVisible();
  await expect(panel.getByText("Online", { exact: true })).toBeVisible();

  // 7. runner stopped: the agent goes offline, and the run the workflow queues waits for it.
  // Wait for Offline first, or a later Online check could pass on the old runner's state.
  await stopRunner();
  await expect(panel.getByText("Offline", { exact: true })).toBeVisible({ timeout: 60_000 });
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  const card = page.getByRole("region", { name: "To Do column" }).getByRole("button", { name: /AGT-1 Investigate sync/ });
  const from = (await card.boundingBox())!;
  const to = (await page.getByRole("region", { name: "In Progress column" }).boundingBox())!;
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + from.width / 2 + 20, from.y + from.height / 2, { steps: 5 });
  await page.mouse.move(to.x + to.width / 2, to.y + 120, { steps: 15 });
  await page.mouse.up();
  const moved = page.getByRole("region", { name: "In Progress column" }).getByRole("button", { name: /AGT-1 Investigate sync/ });
  await expect(moved).toBeVisible();
  await moved.click();
  await expect(panel.getByText(`Agent offline — the run starts when ${ADMIN.name}'s runner connects.`)).toBeVisible();
  await expect(panel.getByText("brainstorm · queued · read-only")).toBeVisible();
  await expect(drawer.getByText("started the workflow")).toBeVisible();
  await expect(drawer.getByText("queued a run")).toHaveCount(1);

  // 8. runner back: the queued run starts once and its progress reaches the thread. It is read-only, so its
  // write is denied and touches neither the worktree nor the repo. It ends with the agent's question.
  launch(token);
  await expect(drawer.getByText("started working")).toBeVisible({ timeout: 30_000 });
  await expect(drawer.getByText("Looking at the code")).toBeVisible({ timeout: 15_000 });
  await expect(drawer.getByText("updated the plan (2 steps)")).toBeVisible({ timeout: 15_000 });
  await expect(drawer.getByText(/was denied: /)).toBeVisible({ timeout: 15_000 });
  await expect(drawer.getByText("Which sync bug should I look at first?")).toBeVisible({ timeout: 15_000 });
  await expect(drawer.getByText("finished: Read-only done")).toBeVisible({ timeout: 15_000 });
  await expect(panel.getByText("Waiting: Answer the agent's question")).toBeVisible();
  await expect(drawer.getByText("started working")).toHaveCount(1);
  await shot(page, "task-run");
  expect(existsSync(join(worktree, "README.md"))).toBe(true); // the run's worktree exists...
  expect(existsSync(join(worktree, "notes.txt"))).toBe(false); // ...and the denied write left nothing in it
  expect(existsSync(join(repo, "notes.txt"))).toBe(false);
  // and on the server: exactly 1 run, started and completed once, none failed or cancelled
  const runs: { id: string; status: string; workflow_role: string | null }[] = await (
    await page.request.get("/api/tasks/AGT-1/agent-runs")
  ).json();
  expect(runs.map((r) => [r.workflow_role, r.status])).toEqual([["brainstorm", "completed"]]);
  const activity: { kind?: string; data?: { run_id?: string } }[] = await (
    await page.request.get("/api/tasks/AGT-1/activity?limit=200")
  ).json();
  const runIdsOf = (kind: string) => activity.filter((i) => i.kind === kind).map((i) => i.data?.run_id);
  expect(runIdsOf("agent_run_started")).toEqual([runs[0].id]);
  expect(runIdsOf("agent_run_completed")).toEqual([runs[0].id]);
  expect(runIdsOf("agent_run_failed")).toEqual([]);
  expect(runIdsOf("agent_run_cancelled")).toEqual([]);

  // 9. MCP create_task: the new task shows up on the open board without a reload
  // (same page, so its live socket has been open all along)
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(page.getByRole("region", { name: "In Progress column" }).getByText("Investigate sync")).toBeVisible();
  const created = await request.post("/api/mcp", {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json, text/event-stream",
      "Content-Type": "application/json",
    },
    data: {
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: { name: "create_task", arguments: { project_key: "AGT", title: "Made over MCP" } },
    },
  });
  expect(created.ok()).toBeTruthy();
  expect(JSON.stringify(await created.json())).toContain("Made over MCP");
  await expect(page.getByRole("region", { name: "Backlog column" }).getByText("Made over MCP")).toBeVisible({
    timeout: 5_000,
  });

  if (SHOTS) {
    await page.goto("/admin/agents");
    await expect(page.getByText(AGENT_NAME)).toBeVisible();
    await shot(page, "admin-agents");
  }
});
