import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type BrowserContext } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { buildBinaries, mintLinkedRunnerToken, onPrompt, say, startRunner, type RunnerHandle } from "./helpers/runner";

/**
 * A freestyle chat on project FRE: each message is a turn that does what it asks, in the chat's own worktree; the chat
 * waits for the next message after each reply, and End chat offers the round to the board with the done column.
 * Needs the Go toolchain and git on the PATH.
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;
const KEY = "FRE-1";
const FREESTYLE = "# Freestyle: do what the person asks, one turn at a time";

const SCENARIO = [
  onPrompt(
    FREESTYLE,
    onPrompt(
      "Add a notes file",
      { write: { path: "notes.txt", content: "notes\n" } },
      { commit: { message: "docs: add notes.txt", all: true } },
      say(`Created notes.txt on megoo/${KEY}`),
    ),
    onPrompt(
      "rename it",
      { write: { path: "NOTES.md", content: "# notes\n" } },
      { commit: { message: "docs: rename notes to NOTES.md", all: true } },
      say("Renamed to NOTES.md"),
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

test("a freestyle chat: two turns, then End chat", async ({ browser }) => {
  test.setTimeout(240_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-freestyle-"));
  leftovers.work = work;
  const ctx = await browser.newContext();
  leftovers.ctx = ctx;
  const ui = await ctx.newPage();
  await setupOrSignIn(ui);
  const request = ui.request;

  const me = (await get<{ user: { id: string } }>(request, "/api/auth/me")).user.id;
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Freestyle Team", description: "" });
  expect((await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB })).ok()).toBeTruthy();
  await post(request, "/api/projects", { key: "FRE", name: "Freestyle Demo", description: "", team_ids: [team.id] });
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
    data: { bindings: [{ project_ref: "FRE", local_path: repo }] },
    headers: WEB,
  });
  expect(bound.ok(), await bound.text()).toBeTruthy();
  const token = await mintLinkedRunnerToken(request, agent.id, "Freestyle");
  leftovers.runner = startRunner({
    url: BASE, token, home: join(work, "home"), adapterOverride: bins.fakeAgent, scenario: SCENARIO, runnerBin: bins.runner,
  });
  await expect
    .poll(async () => (await get<Agent[]>(request, "/api/agents/mine")).find((a) => a.id === agent.id)?.status, { timeout: 20_000 })
    .toBe("online");

  // 1. start a freestyle chat
  await ui.goto("/projects/FRE/chats");
  await ui.getByRole("button", { name: "New chat" }).click();
  await ui.getByRole("group", { name: "How should the agent work?" }).getByLabel("Freestyle").check();
  await ui.getByLabel("Message").fill("Add a notes file");
  await ui.getByRole("button", { name: "Start chat" }).click();
  await expect(ui).toHaveURL(/\/chats\/[0-9a-f-]{36}$/);
  const view = ui.getByRole("main");
  await expect(view.locator("header").getByText("Freestyle", { exact: true })).toBeVisible();
  // the reply shows as the agent's message and again in "…finished: <reply>": the message comes first
  await expect(view.getByText(`Created notes.txt on megoo/${KEY}`).first()).toBeVisible({ timeout: 60_000 });
  await expect(view.locator("[data-chat]").getByText("waiting for your reply", { exact: true })).toBeVisible({ timeout: 30_000 });

  // 2. a second message is the next turn
  const box = view.getByRole("textbox", { name: `Message ${AGENT_NAME}` });
  await box.fill("rename it");
  await view.getByRole("button", { name: "Send", exact: true }).click();
  await expect(view.getByText("Renamed to NOTES.md").first()).toBeVisible({ timeout: 60_000 });
  await expect(view.locator("[data-chat]").getByText("waiting for your reply", { exact: true })).toBeVisible({ timeout: 30_000 });

  // 3. both commits are on the chat's branch
  const branches = git(repo, "branch", "--list", "megoo/FRE-1-*", "--format=%(refname:short)").trim().split("\n").filter(Boolean);
  expect(branches).toHaveLength(1);
  const log = git(repo, "log", "--format=%s", branches[0]);
  expect(log).toContain("docs: add notes.txt");
  expect(log).toContain("docs: rename notes to NOTES.md");

  // 4. End chat: it asks, then offers the round to the board with the done column
  await view.getByRole("button", { name: "End chat" }).click();
  await ui.getByRole("alertdialog", { name: "End this chat?" }).getByRole("button", { name: "End chat" }).click();
  const dialog = ui.getByRole("dialog", { name: "Add this to the board?" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Column")).toContainText("Done");
  await dialog.getByRole("button", { name: "No, just end it" }).click();
  await expect(dialog).toBeHidden();
  await expect(view.getByText("This chat has ended.")).toBeVisible();
});
