import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type BrowserContext } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { buildBinaries, mcp, mintLinkedRunnerToken, onPrompt, say, startRunner, type RunnerHandle } from "./helpers/runner";

/**
 * A freestyle chat on project CRD: asked for the test results, the agent shows them as a card (two tiles, tabs, a
 * link to a board task) and replies in text; the chat's thread draws the card, and its tabs and task link work.
 * Needs the Go toolchain and git on the PATH.
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;
const KEY = "CRD-1";
const FREESTYLE = "# Freestyle: do what the person asks, one turn at a time";

const CARD = {
  components: [
    { id: "root", component: "Column", children: ["tiles", "tabs"] },
    { id: "tiles", component: "Row", children: ["passed", "failed"] },
    { id: "passed", component: "StatTile", label: "Passed", value: "412", tone: "good" },
    { id: "failed", component: "StatTile", label: "Failed", value: "3", tone: "bad" },
    { id: "tabs", component: "Tabs", tabs: [{ title: "Failing", child: "failing" }, { title: "Notes", child: "notes" }] },
    { id: "failing", component: "List", children: ["link"] },
    { id: "link", component: "TaskLink", task: "CRD-2", label: "Login times out" },
    { id: "notes", component: "Text", text: "Two failures are flaky." },
  ],
};

const SCENARIO = [
  onPrompt(
    FREESTYLE,
    onPrompt(
      "Show me the test results",
      mcp("show_card", { key: KEY, title: "Test results", text: "412 passed, 3 failed.", card: CARD }),
      say("Here are the test results."),
    ),
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

function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", ["-c", "user.name=E2E", "-c", "user.email=e2e@acme.io", ...args], { cwd, stdio: "pipe" }).toString();
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

test("an agent shows a card in a chat, and the thread draws it", async ({ browser }) => {
  test.setTimeout(240_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-cards-"));
  leftovers.work = work;
  const ctx = await browser.newContext();
  leftovers.ctx = ctx;
  const ui = await ctx.newPage();
  await setupOrSignIn(ui);
  const request = ui.request;

  const me = (await get<{ user: { id: string } }>(request, "/api/auth/me")).user.id;
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Cards Team", description: "" });
  expect((await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB })).ok()).toBeTruthy();
  await post(request, "/api/projects", { key: "CRD", name: "Cards Demo", description: "", team_ids: [team.id] });
  // no sprints, so the board shows every task and opens the drawer the card's link asks for
  expect((await request.patch("/api/projects/CRD", { data: { sprints_enabled: false }, headers: WEB })).ok()).toBeTruthy();
  const bins = buildBinaries(join(work, "bin"));
  const repo = join(work, "repo");
  mkdirSync(repo);
  git(repo, "init", "-q");
  writeFileSync(join(repo, "README.md"), "# demo\n");
  git(repo, "add", ".");
  git(repo, "commit", "-q", "-m", "init");
  type Agent = { id: string; name: string; status: string };
  const mine = await get<Agent[]>(request, "/api/agents/mine");
  const agent = mine.find((a) => a.name === AGENT_NAME) ?? (await post<Agent>(request, "/api/agents", { program: "claude_code" }));
  const bound = await request.put(`/api/agents/${agent.id}/bindings`, {
    data: { bindings: [{ project_ref: "CRD", local_path: repo }] },
    headers: WEB,
  });
  expect(bound.ok(), await bound.text()).toBeTruthy();
  const token = await mintLinkedRunnerToken(request, agent.id, "Cards");
  leftovers.runner = startRunner({
    url: BASE, token, home: join(work, "home"), adapterOverride: bins.fakeAgent, scenario: SCENARIO, runnerBin: bins.runner,
  });
  await expect
    .poll(async () => (await get<Agent[]>(request, "/api/agents/mine")).find((a) => a.id === agent.id)?.status, { timeout: 20_000 })
    .toBe("online");

  // 1. start a freestyle chat; its round is CRD-1, and the task the card links to is CRD-2 on the board
  await ui.goto("/projects/CRD/chats");
  await ui.getByRole("button", { name: "New chat" }).click();
  await ui.getByRole("group", { name: "How should the agent work?" }).getByLabel("Freestyle").check();
  await ui.getByLabel("Message").fill("Show me the test results");
  await ui.getByRole("button", { name: "Start chat" }).click();
  await expect(ui).toHaveURL(/\/chats\/[0-9a-f-]{36}$/);
  const linked = await post<{ key: string }>(request, "/api/projects/CRD/tasks", { title: "Login times out", type: "task" });
  expect(linked.key).toBe("CRD-2");

  // 2. the reply, and the card as its own row: its title as the heading, the tiles, the tabs
  const view = ui.getByRole("main");
  await expect(view.getByText("Here are the test results.")).toBeVisible({ timeout: 60_000 });
  const card = view.locator("[data-thread-card]");
  await expect(card).toBeVisible();
  await expect(card.getByRole("heading", { name: "Test results" })).toBeVisible();
  await expect(card.getByRole("group", { name: "Passed" })).toContainText("412");
  await expect(card.getByRole("group", { name: "Failed" })).toContainText("3");
  await expect(view.getByText("showed a card")).toBeVisible();

  // 3. the tabs switch, and the task link opens the board's drawer
  await card.getByRole("tab", { name: "Notes" }).click();
  await expect(card.getByText("Two failures are flaky.")).toBeVisible();
  await card.getByRole("tab", { name: "Failing" }).click();
  await card.getByRole("link", { name: "CRD-2" }).click();
  await expect(ui).toHaveURL(/\/projects\/CRD\/board\?task=CRD-2/);
  const drawer = ui.getByRole("dialog", { name: "CRD-2" });
  await expect(drawer).toBeVisible({ timeout: 15_000 });
  await expect(drawer.getByText("Login times out").first()).toBeVisible();

  // 4. the round's activity holds the card, with its title
  type Item = { type: string; card?: { title: string } };
  const activity = await get<Item[]>(request, `/api/tasks/${KEY}/activity?limit=200`);
  expect(activity.find((i) => i.type === "card")?.card?.title).toBe("Test results");
});
