import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type BrowserContext } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { buildBinaries, mcp, mintLinkedRunnerToken, onPrompt, say, startRunner, type RunnerHandle } from "./helpers/runner";

/**
 * Plan 20: a message for the agent reaches it in the turn it is working on (ACP steering), and one sent while no
 * run is going is given to its next run. Needs the Go toolchain and git on the PATH. Project key TLA.
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;
const KEY = "TLA-1";
const BRAINSTORM = "# Brainstorm: turn the task into an approved design";
const PLAN = "# Plan: break the approved design into steps";

const SCENARIO = onPrompt(
  `## Task ${KEY}\n`,
  onPrompt(
    BRAINSTORM,
    say("Thinking about retries"),
    { await_steer_ms: 60_000 }, // says "steered: <the instruction's last line>"
    mcp("submit_design", { key: KEY, markdown: "# Retries\n\nRetry three times." }),
  ),
  onPrompt(
    PLAN,
    onPrompt("> Log retries", say("Got the instruction: Log retries")),
    mcp("submit_plan", { key: KEY, markdown: "# Plan", steps: [{ title: "Retry", detail: "One file." }] }),
  ),
);

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

function git(cwd: string, ...args: string[]) {
  execFileSync("git", ["-c", "user.name=E2E", "-c", "user.email=e2e@acme.io", ...args], { cwd, stdio: "pipe" });
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

test("telling the agent something while it works, and before its next run", async ({ browser }) => {
  test.setTimeout(240_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-tell-"));
  leftovers.work = work;
  const ctx = await browser.newContext();
  leftovers.ctx = ctx;
  const ui = await ctx.newPage();
  await setupOrSignIn(ui);
  const request = ui.request;

  const team = await post<{ id: string }>(request, "/api/teams", { name: "Tell Team", description: "" });
  await post(request, "/api/projects", { key: "TLA", name: "Tell Demo", description: "", team_ids: [team.id] });
  expect((await request.patch("/api/projects/TLA", { data: { sprints_enabled: false }, headers: WEB })).ok()).toBeTruthy();
  const bins = buildBinaries(join(work, "bin"));
  const repo = join(work, "repo");
  mkdirSync(repo);
  git(repo, "init", "-q");
  writeFileSync(join(repo, "README.md"), "# payments\n");
  git(repo, "add", ".");
  git(repo, "commit", "-q", "-m", "init");
  type Agent = { id: string; name: string; status: string };
  const mine = await get<Agent[]>(request, "/api/agents/mine");
  const agent = mine.find((a) => a.name === AGENT_NAME) ?? (await post<Agent>(request, "/api/agents", { program: "claude_code" }));
  const bound = await request.put(`/api/agents/${agent.id}/bindings`, {
    data: { bindings: [{ project_ref: "TLA", local_path: repo }] },
    headers: WEB,
  });
  expect(bound.ok(), await bound.text()).toBeTruthy();
  const token = await mintLinkedRunnerToken(request, agent.id, "Tell");
  const launch = () => {
    leftovers.runner = startRunner({
      url: BASE,
      token,
      home: join(work, "home"),
      adapterOverride: bins.fakeAgent,
      scenario: [SCENARIO],
      runnerBin: bins.runner,
    });
  };
  launch();
  const status = async () => (await get<Agent[]>(request, "/api/agents/mine")).find((a) => a.id === agent.id)?.status;
  await expect.poll(status, { timeout: 20_000 }).toBe("online");

  await post(request, "/api/projects/TLA/tasks", { title: "Retry payments", type: "task", assignee_agent_id: agent.id });
  await ui.goto(`/projects/TLA/board?task=${KEY}`);
  const drawer = ui.getByRole("dialog", { name: KEY });
  await post(request, `/api/tasks/${KEY}/workflow/start`, {});
  await expect(drawer.getByText("Thinking about retries")).toBeVisible({ timeout: 30_000 });

  // 1. while the brainstorm run works: the task isn't done, so the box already sends to the agent; @mentioning it
  // keeps it so
  const box = drawer.getByRole("textbox", { name: "Add a comment" });
  await expect(drawer.getByRole("switch", { name: `Send to ${AGENT_NAME}` })).toHaveAttribute("aria-checked", "true");
  await box.fill(`@${ADMIN.name.split(" ")[0]}`);
  // the list opens over the page, outside the drawer's own box
  await ui.getByRole("listbox", { name: "Mention someone" }).getByRole("option", { name: /agent on this task/ }).click();
  await expect(drawer.getByRole("switch", { name: `Send to ${AGENT_NAME}` })).toHaveAttribute("aria-checked", "true");
  await expect(drawer.getByText(/is working on the design: it reads this straight away/)).toBeVisible();
  await box.pressSequentially("Use RetryPolicy");
  await drawer.getByRole("button", { name: "Send to agent" }).click();
  await expect(drawer.getByText(`${ADMIN.name} → ${AGENT_NAME}`)).toBeVisible();
  await expect(drawer.getByText(/read while working/)).toBeVisible({ timeout: 15_000 });
  await expect(drawer.getByText(/steered: .*Use RetryPolicy/).first()).toBeVisible({ timeout: 15_000 });
  await expect(drawer.getByRole("switch", { name: `Send to ${AGENT_NAME}` })).toHaveAttribute("aria-checked", "true");

  // 2. the design is waiting for approval and no run is going: the next message waits
  await expect
    .poll(async () => (await get<{ needs: string | null }>(request, `/api/tasks/${KEY}/workflow`)).needs, { timeout: 30_000 })
    .toBe("design_approval");
  await expect(drawer.getByText(/isn't working right now/)).toBeVisible();
  await box.fill("Log retries");
  await drawer.getByRole("button", { name: "Send to agent" }).click();
  await expect(drawer.getByText("waiting: goes to its next run")).toBeVisible();

  // 3. approving the design starts the plan run, which is given the waiting message at its start
  await post(request, `/api/tasks/${KEY}/documents/design/1/decision`, { approve: true });
  await expect(drawer.getByText("Got the instruction: Log retries").first()).toBeVisible({ timeout: 30_000 });
  await expect(drawer.getByText("given at the start of the plan run")).toBeVisible({ timeout: 15_000 });
});
