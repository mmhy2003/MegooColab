import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type BrowserContext } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { buildBinaries, mcp, mintLinkedRunnerToken, onPrompt, say, startRunner, type RunnerHandle } from "./helpers/runner";

/**
 * Agent crons: a cron written with the schedule helper (a mistake shown, then a preset), run now on the project's
 * agent in a throwaway copy of origin's default branch, reports a finding that becomes a task labelled "from cron".
 * Needs the Go toolchain and git on the PATH.
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;
const JOB = "Check the dependencies for e2e.";

const SCENARIO = [
  onPrompt(JOB, mcp("submit_cron_report", {
    summary: "One vulnerable package.",
    findings: [{ title: "jsonwebtoken 8.5.1", detail: "Signature bypass; move to 9.0.2.", new_task: true }],
    checked: "42 packages",
  }), say("done")),
];

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
    .toString().trim();
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

test("a cron from its schedule to a report and a task", async ({ browser }) => {
  test.setTimeout(240_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-crons-"));
  leftovers.work = work;
  const ctx = await browser.newContext();
  leftovers.ctx = ctx;
  const ui = await ctx.newPage();
  await setupOrSignIn(ui);
  const request = ui.request;

  // project JOB, a repository whose origin's main moved ahead, the admin's agent bound to it, and the runner
  const me = (await get<{ user: { id: string } }>(request, "/api/auth/me")).user.id;
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Jobs Team", description: "" });
  expect((await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB })).ok()).toBeTruthy();
  await post(request, "/api/projects", { key: "JOB", name: "Jobs", description: "", team_ids: [team.id] });
  const bins = buildBinaries(join(work, "bin"));
  const repo = join(work, "repo");
  mkdirSync(repo);
  git(repo, "init", "-q", "-b", "main");
  writeFileSync(join(repo, "README.md"), "# jobs\n");
  git(repo, "add", ".");
  git(repo, "commit", "-q", "-m", "init");
  const origin = join(work, "origin.git");
  git(work, "clone", "-q", "--bare", repo, origin);
  git(repo, "remote", "add", "origin", origin);
  const ahead = join(work, "ahead");
  git(work, "clone", "-q", origin, ahead);
  writeFileSync(join(ahead, "ahead.txt"), "ahead\n");
  git(ahead, "add", ".");
  git(ahead, "commit", "-q", "-m", "ahead");
  git(ahead, "push", "-q", "origin", "HEAD:main");
  const originHead = git(ahead, "rev-parse", "HEAD");
  type Agent = { id: string; name: string; status: string };
  const mine = await get<Agent[]>(request, "/api/agents/mine");
  const agent = mine.find((a) => a.name === AGENT_NAME) ?? (await post<Agent>(request, "/api/agents", { program: "claude_code" }));
  const bound = await request.put(`/api/agents/${agent.id}/bindings`, {
    data: { bindings: [{ project_ref: "JOB", local_path: repo }] },
    headers: WEB,
  });
  expect(bound.ok(), await bound.text()).toBeTruthy();
  const token = await mintLinkedRunnerToken(request, agent.id, "Crons");
  leftovers.runner = startRunner({
    url: BASE, token, home: join(work, "home"), adapterOverride: bins.fakeAgent, scenario: SCENARIO, runnerBin: bins.runner,
  });
  await expect
    .poll(async () => (await get<Agent[]>(request, "/api/agents/mine")).find((a) => a.id === agent.id)?.status, { timeout: 20_000 })
    .toBe("online");

  // 1. a new cron: a mistake in the schedule is named and blocks saving; a preset fixes it, in plain words
  await ui.goto("/projects/JOB/crons");
  await ui.getByRole("button", { name: "New cron" }).click();
  const dialog = ui.getByRole("dialog");
  await dialog.getByLabel("Name").fill("Nightly dependency check");
  await dialog.getByLabel("What the agent should do").fill(JOB);
  await dialog.getByLabel("Schedule").fill("0 25 * * *");
  await expect(dialog.getByText("Hour must be 0–23 (you wrote 25)")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Save cron" })).toBeDisabled();
  await dialog.getByRole("button", { name: "Weekdays at…" }).click();
  await expect(dialog.getByText("At 09:00, Monday through Friday")).toBeVisible();
  await expect(dialog.getByText(/Next runs:/)).toBeVisible();
  await dialog.getByLabel(/Report, and open tasks for real problems/).check();
  await dialog.getByRole("button", { name: "Save cron" }).click();
  await expect(ui.getByRole("link", { name: "Nightly dependency check" })).toBeVisible();

  // 2. run it now: the agent reports one finding, which becomes a task
  await ui.getByRole("button", { name: "Run now" }).click();
  type Cron = { id: string };
  const [cron] = await get<Cron[]>(request, "/api/projects/JOB/crons");
  type Run = { status: string; commit: string | null };
  await expect
    .poll(async () => (await get<Run[]>(request, `/api/projects/JOB/crons/${cron.id}/runs`))[0]?.status, { timeout: 60_000 })
    .toBe("done");
  const [run] = await get<Run[]>(request, `/api/projects/JOB/crons/${cron.id}/runs`);
  expect(run.commit).toBe(originHead); // it worked on origin's main, fetched first

  // 3. the cron page shows the report with the new task, which carries the "from cron" label
  await ui.getByRole("link", { name: "Nightly dependency check" }).click();
  await expect(ui.getByText("One vulnerable package.")).toBeVisible();
  await expect(ui.getByRole("link", { name: "JOB-1 created" })).toBeVisible();
  await expect(ui.getByText(`commit ${originHead.slice(0, 7)}`, { exact: false })).toBeVisible();
  const task = await get<{ title: string; labels: { name: string }[] }>(request, "/api/tasks/JOB-1");
  expect(task.title).toBe("jsonwebtoken 8.5.1");
  expect(task.labels.map((l) => l.name)).toContain("from cron");

  // 4. on a phone the Crons tab and the cron's page don't scroll sideways
  const phone = await ctx.newPage();
  await phone.setViewportSize({ width: 280, height: 640 });
  for (const path of ["/projects/JOB/crons", `/projects/JOB/crons/${cron.id}`]) {
    await phone.goto(path);
    await expect(phone.getByText("Nightly dependency check").first()).toBeVisible();
    expect(await phone.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(280);
  }
  await phone.close();
});
