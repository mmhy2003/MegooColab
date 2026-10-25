import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { buildBinaries, startRunner, type Binaries, type RunnerHandle } from "./helpers/runner";

/**
 * End-to-end test of Plan 2: UI -> server -> runner -> (fake) agent and back.
 * Needs the Go toolchain and git on the PATH; the runner runs on the host and
 * connects to the stack under test. See README "Agents end-to-end test".
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const SHOTS = process.env.E2E_SCREENSHOT_DIR; // optional: also capture review screenshots
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;

const say = (text: string) => ({ say: text });
const SCENARIO_WORKSPACE = [
  say("Looking at the code"),
  { plan: [["Read the code", "completed"], ["Write notes", "in_progress"]] },
  { write: { path: "notes.txt", content: "hello\n" } },
  say("Done"),
];
const SCENARIO_WRITE_ATTEMPT = [
  say("Trying to write"),
  { write: { path: "notes.txt", content: "tampered\n" } },
  say("Read-only done"),
];
const SCENARIO_BACK = [say("Back online")];

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

function git(cwd: string, ...args: string[]) {
  execFileSync("git", ["-c", "user.name=E2E", "-c", "user.email=e2e@acme.io", ...args], { cwd, stdio: "pipe" });
}

test("agents end to end", async ({ browser, request }) => {
  test.setTimeout(240_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-agents-"));
  const bins: Binaries = buildBinaries(join(work, "bin"));
  const repo = join(work, "repo");
  mkdirSync(repo);
  git(repo, "init", "-q");
  writeFileSync(join(repo, "README.md"), "# demo\n");
  git(repo, "add", ".");
  git(repo, "commit", "-q", "-m", "init");
  const home = join(work, "home");
  let runner: RunnerHandle | undefined;
  const launch = (token: string, scenario: unknown[]) => {
    runner = startRunner({ url: BASE, token, home, adapterOverride: bins.fakeAgent, scenario, runnerBin: bins.runner });
  };

  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  try {
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
    launch(token, SCENARIO_WORKSPACE);
    await expect(page.getByText("Online")).toBeVisible({ timeout: 5_000 });
    await shot(page, "agents-settings");
    const agents = await (await page.request.get("/api/agents/mine")).json();
    const agentId: string = agents[0].id;
    const worktree = join(home, "cache", "megoocolab", "worktrees", agentId, "AGT-1");

    // 6. a task assigned to the agent
    await page.goto("/projects/AGT/board");
    await page.getByLabel("New task in To Do").fill("Investigate sync");
    await page.getByLabel("New task in To Do").press("Enter");
    await page.goto("/projects/AGT/board?task=AGT-1");
    const drawer = page.getByRole("dialog", { name: "AGT-1" });
    await expect(drawer).toBeVisible();
    await drawer.getByLabel("Assignee").selectOption({ label: AGENT_NAME });
    const panel = drawer.getByRole("region", { name: "Agent" });
    await expect(panel).toBeVisible();

    // 7. workspace run: edits land in the worktree, not in the repo
    await panel.getByLabel("Run policy").selectOption("workspace");
    await panel.getByRole("button", { name: "Run agent" }).click();
    await expect(drawer.getByText("started working")).toBeVisible({ timeout: 15_000 });
    await expect(drawer.getByText("Looking at the code")).toBeVisible({ timeout: 15_000 });
    await expect(drawer.getByText("changed notes.txt (+1 −0)")).toBeVisible({ timeout: 15_000 });
    await expect(drawer.getByText("finished: Done")).toBeVisible({ timeout: 15_000 });
    expect(existsSync(join(worktree, "notes.txt"))).toBe(true);
    expect(readFileSync(join(worktree, "notes.txt"), "utf8")).toBe("hello\n");
    expect(existsSync(join(repo, "notes.txt"))).toBe(false);
    await shot(page, "task-run");

    // 8. read-only run whose agent tries to write: denied, file untouched
    await runner!.stop();
    launch(token, SCENARIO_WRITE_ATTEMPT);
    await expect(panel.getByText("Online", { exact: true })).toBeVisible({ timeout: 10_000 });
    await panel.getByLabel("Run policy").selectOption("read_only");
    await panel.getByRole("button", { name: "Run agent" }).click();
    await expect(drawer.getByText(/was denied: /)).toBeVisible({ timeout: 15_000 });
    await expect(drawer.getByText("finished: Read-only done")).toBeVisible({ timeout: 15_000 });
    expect(readFileSync(join(worktree, "notes.txt"), "utf8")).toBe("hello\n");

    // 9. runner stopped: agent offline, a new run waits
    await runner!.stop();
    await expect(panel.getByText("Offline", { exact: true })).toBeVisible({ timeout: 60_000 });
    await expect(panel.getByText(`Agent offline — the run starts when ${ADMIN.name}'s runner connects.`)).toBeVisible();
    await panel.getByRole("button", { name: "Run agent" }).click();
    await expect(panel.getByText(/queued · read-only/)).toBeVisible();
    await expect(drawer.getByText("queued a run")).toHaveCount(3); // one per run so far

    // 10. runner back: the queued run starts once and completes
    launch(token, SCENARIO_BACK);
    await expect(drawer.getByText("finished: Back online")).toBeVisible({ timeout: 30_000 });
    await expect(drawer.getByText("started working")).toHaveCount(3);
    await expect(drawer.getByText("finished: Back online")).toHaveCount(1);

    // 11. MCP create_task: the new task shows up on the open board without a reload
    // (same page, so its live socket has been open all along)
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(page.getByRole("region", { name: "To Do column" }).getByText("Investigate sync")).toBeVisible();
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
  } finally {
    await runner?.stop();
    if (process.env.E2E_RUNNER_LOG) console.log(runner?.output());
    await ctx.close();
  }
});
