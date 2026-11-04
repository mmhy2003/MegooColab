import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type BrowserContext, type Page } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { buildBinaries, mcp, mintLinkedRunnerToken, onPrompt, readReports, startRunner, type RunnerHandle } from "./helpers/runner";

/**
 * Secrets: a personal and a project secret, added through the pages, reach a fake agent's environment and are named in
 * its prompt; the values never come back: the runner blanks what the agent says, the server what it writes through MCP.
 * Needs the Go toolchain and git on the PATH.
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;
const PROJECT_VALUE = "staging-pass-456";
const PERSONAL_VALUE = "personal-token-123";
const BRAINSTORM = "# Brainstorm: turn the task into an approved design";

const SCENARIO = [
  onPrompt(
    BRAINSTORM,
    { say_env: "STAGING_DB_PASSWORD" },
    mcp("ask_human", { key: "SEC-1", question: `Is ${PROJECT_VALUE} the right one?`, choices: [] }),
    { say_env: "MY_TOKEN" },
  ),
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

function git(cwd: string, ...args: string[]) {
  execFileSync("git", ["-c", "user.name=E2E", "-c", "user.email=e2e@acme.io", ...args], { cwd, stdio: "pipe" });
}

async function addSecret(ui: Page, name: string, description: string, value: string) {
  await ui.getByRole("button", { name: "Add secret" }).click();
  const dialog = ui.getByRole("dialog");
  await dialog.getByLabel("Environment variable name").fill(name);
  await dialog.getByLabel("What it is (the agent reads this)").fill(description);
  await dialog.getByLabel("Value", { exact: true }).fill(value);
  await dialog.getByRole("button", { name: "Save secret" }).click();
  await expect(ui.getByText(name, { exact: true })).toBeVisible();
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

test("secrets reach the agent's environment by name, and their values never come back", async ({ browser }) => {
  test.setTimeout(240_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-secrets-"));
  leftovers.work = work;
  const ctx = await browser.newContext();
  leftovers.ctx = ctx;
  const ui = await ctx.newPage();
  await setupOrSignIn(ui);
  const request = ui.request;

  // project SEC, the admin's agent bound to a repository, and the runner with the scenario
  const me = (await get<{ user: { id: string } }>(request, "/api/auth/me")).user.id;
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Secrets Team", description: "" });
  expect((await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB })).ok()).toBeTruthy();
  await post(request, "/api/projects", { key: "SEC", name: "Secrets", description: "", team_ids: [team.id] });
  const bins = buildBinaries(join(work, "bin"));
  const repo = join(work, "repo");
  mkdirSync(repo);
  git(repo, "init", "-q");
  writeFileSync(join(repo, "README.md"), "# secrets\n");
  git(repo, "add", ".");
  git(repo, "commit", "-q", "-m", "init");
  type Agent = { id: string; name: string; status: string };
  const mine = await get<Agent[]>(request, "/api/agents/mine");
  const agent = mine.find((a) => a.name === AGENT_NAME) ?? (await post<Agent>(request, "/api/agents", { program: "claude_code" }));
  const bound = await request.put(`/api/agents/${agent.id}/bindings`, {
    data: { bindings: [{ project_ref: "SEC", local_path: repo }] },
    headers: WEB,
  });
  expect(bound.ok(), await bound.text()).toBeTruthy();

  // 1. a personal secret and a project secret, through their pages
  await ui.goto("/settings/secrets");
  await addSecret(ui, "MY_TOKEN", "My personal API token", PERSONAL_VALUE);
  await ui.goto("/projects/SEC/settings?tab=secrets");
  await addSecret(ui, "STAGING_DB_PASSWORD", "Staging Postgres password", PROJECT_VALUE);
  // after a reload a value is dots, never the value
  await ui.reload();
  await expect(ui.getByText("STAGING_DB_PASSWORD", { exact: true })).toBeVisible();
  expect(await ui.content()).not.toContain(PROJECT_VALUE);

  const reports = join(work, "reports");
  const token = await mintLinkedRunnerToken(request, agent.id, "Secrets");
  leftovers.runner = startRunner({
    url: BASE, token, home: join(work, "home"), adapterOverride: bins.fakeAgent, scenario: SCENARIO, runnerBin: bins.runner,
    env: { FAKEAGENT_REPORT_DIR: reports },
  });
  await expect
    .poll(async () => (await get<Agent[]>(request, "/api/agents/mine")).find((a) => a.id === agent.id)?.status, { timeout: 20_000 })
    .toBe("online");

  // 2. a chat: the agent says both values and asks a question holding one
  await ui.goto("/projects/SEC/chats");
  await ui.getByRole("button", { name: "New chat" }).click();
  await ui.getByLabel("Message").fill("Check the staging database");
  await ui.getByRole("button", { name: "Start chat" }).click();
  await expect(ui).toHaveURL(/\/chats\/[0-9a-f-]{36}$/);
  const view = ui.getByRole("main");
  // the server blanked the value out of the agent's question
  await expect(view.getByText("Is [STAGING_DB_PASSWORD] the right one?")).toBeVisible({ timeout: 60_000 });
  const html = await ui.content();
  expect(html).not.toContain(PROJECT_VALUE);
  expect(html).not.toContain(PERSONAL_VALUE);

  // 3. the runner blanked what the agent said
  await expect
    .poll(async () => (await get<{ summary: string | null }[]>(request, "/api/tasks/SEC-1/agent-runs"))[0]?.summary ?? "",
      { timeout: 30_000 })
    .toContain("[MY_TOKEN]");
  const runs = JSON.stringify(await get(request, "/api/tasks/SEC-1/agent-runs"));
  expect(runs).not.toContain(PROJECT_VALUE);
  expect(runs).not.toContain(PERSONAL_VALUE);

  // 4. the agent's prompt named both secrets, and held neither value
  const prompts = readReports(reports).flatMap((r) => r.prompts ?? []).join("\n");
  expect(prompts).toContain("## Secrets you can use");
  expect(prompts).toContain("- MY_TOKEN — My personal API token");
  expect(prompts).toContain("- STAGING_DB_PASSWORD — Staging Postgres password");
  expect(prompts).not.toContain(PROJECT_VALUE);
  expect(prompts).not.toContain(PERSONAL_VALUE);
});
