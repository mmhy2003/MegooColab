import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type BrowserContext } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { buildBinaries, mcp, mintLinkedRunnerToken, onPrompt, say, startRunner, type RunnerHandle } from "./helpers/runner";

/**
 * Writing a Knowledge Base document with an agent: the agent's first turn adds a section and removes one, one change is
 * undone, the person types a line of their own, a second request changes a paragraph and keeps that line, and the draft
 * is saved as a revision credited to the person with the agent. Needs the Go toolchain and git on the PATH.
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;
const BRIEF = "Tidy the deploy runbook for on-call engineers";
const REQUEST = "shorten the prerequisites";

const ORIGINAL = [
  "# Deploying payments",
  "## Overview",
  "This runbook covers deploying payments-api.",
  "## Prerequisites",
  "Before starting, make sure you have access to the production cluster and the on-call group.",
  "## FAQ",
  "Q: How do I deploy? A: Follow the steps.",
  "## Smoke checks",
  "Run the checkout smoke test.",
].join("\n\n");
// turn 1: the FAQ goes, a Rollback section comes
const TURN1 = ORIGINAL.replace("\n\n## FAQ\n\nQ: How do I deploy? A: Follow the steps.", "")
  + "\n\n## Rollback\n\nUndo with kubectl rollout undo.";
// the FAQ undone, the rollback kept, then the person's own line under the overview
const EDITED = ORIGINAL.replace("deploying payments-api.", "deploying payments-api.\n\nOwner: payments team.")
  + "\n\n## Rollback\n\nUndo with kubectl rollout undo.";
// turn 2: only the prerequisites change; the person's line stays
const TURN2 = EDITED.replace(
  "Before starting, make sure you have access to the production cluster and the on-call group.",
  "You need prod cluster access and on-call membership.",
);

const SCENARIO = [
  onPrompt(`## This turn's request\n\n${BRIEF}`, mcp("kb_draft_read", {}),
    mcp("kb_draft_submit", { body_md: TURN1, reply: "Dropped the FAQ and added a rollback section." }), say("done")),
  onPrompt(`## This turn's request\n\n${REQUEST}`, mcp("kb_draft_read", {}),
    mcp("kb_draft_submit", { body_md: TURN2, reply: "Shortened the prerequisites." }), say("done")),
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

test("a document written with an agent, from the first draft to a saved revision", async ({ browser }) => {
  test.setTimeout(240_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-kbdrafts-"));
  leftovers.work = work;
  const ctx = await browser.newContext();
  leftovers.ctx = ctx;
  const ui = await ctx.newPage();
  await setupOrSignIn(ui);
  const request = ui.request;

  // project KBW, its document, the admin's agent bound to a repository, and the runner with the scenario
  const me = (await get<{ user: { id: string } }>(request, "/api/auth/me")).user.id;
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Docs Team", description: "" });
  expect((await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB })).ok()).toBeTruthy();
  const project = await post<{ id: string }>(request, "/api/projects", {
    key: "KBW", name: "Runbooks", description: "", team_ids: [team.id],
  });
  const spaces = await get<{ id: string; project_id: string | null }[]>(request, "/api/kb/spaces");
  const space = spaces.find((s) => s.project_id === project.id)!;
  const doc = await post<{ id: string }>(request, `/api/kb/spaces/${space.id}/documents`, {
    title: "Deploying payments", body_md: ORIGINAL,
  });
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
    data: { bindings: [{ project_ref: "KBW", local_path: repo }] },
    headers: WEB,
  });
  expect(bound.ok(), await bound.text()).toBeTruthy();
  const token = await mintLinkedRunnerToken(request, agent.id, "Drafts");
  leftovers.runner = startRunner({
    url: BASE, token, home: join(work, "home"), adapterOverride: bins.fakeAgent, scenario: SCENARIO, runnerBin: bins.runner,
  });
  await expect
    .poll(async () => (await get<Agent[]>(request, "/api/agents/mine")).find((a) => a.id === agent.id)?.status, { timeout: 20_000 })
    .toBe("online");

  // 1. Write with an agent, from the document
  await ui.goto(`/kb/doc/${doc.id}`);
  await ui.getByRole("button", { name: "Write with an agent" }).click();
  await ui.getByLabel("What should the agent change?").fill(BRIEF);
  await ui.getByRole("button", { name: "Start drafting" }).click();
  await expect(ui).toHaveURL(/\/kb\/drafts\/[0-9a-f-]{36}$/);

  // 2. the first turn: a section added, one removed, both marked
  const removed = ui.getByRole("region", { name: "removed by the agent" });
  const added = ui.getByRole("region", { name: "added by the agent" });
  await expect(removed).toBeVisible({ timeout: 60_000 });
  await expect(added).toContainText("Rollback");
  await expect(ui.getByText("Dropped the FAQ and added a rollback section.")).toBeVisible();

  // 3. the removal undone: the FAQ is back, unmarked
  await removed.getByRole("button", { name: "Undo" }).click();
  await expect(removed).toHaveCount(0);
  await expect(ui.getByText("Q: How do I deploy? A: Follow the steps.")).toBeVisible();

  // 4. the person's own line (switching to the editor keeps the open change)
  await ui.getByRole("button", { name: "Edit text" }).click();
  await ui.getByLabel("Body").fill(EDITED);
  await ui.getByRole("button", { name: "Done editing" }).click();
  await expect(ui.getByLabel("Body")).toHaveCount(0);
  await expect(ui.getByText("Owner: payments team.")).toBeVisible();

  // 5. a second request: the prerequisites change, the person's line stays
  await ui.getByLabel("Your request").fill(REQUEST);
  await ui.getByRole("button", { name: "Send" }).click();
  const changed = ui.getByRole("region", { name: "changed by the agent" });
  await expect(changed).toBeVisible({ timeout: 60_000 });
  await expect(changed.locator("ins").first()).toBeVisible();
  await ui.getByRole("button", { name: "Keep all" }).click();
  await expect(changed).toHaveCount(0);

  // 6. on a wide but short screen, the conversation stays in view while the draft scrolls, request box and all
  const wide = await ctx.newPage();
  await wide.setViewportSize({ width: 1280, height: 420 });
  await wide.goto(ui.url());
  const pane = wide.getByRole("region", { name: "Conversation with the agent" });
  await expect(pane).toBeVisible();
  await wide.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await expect.poll(() => wide.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  expect(Math.round((await pane.boundingBox())!.y)).toBe(64);
  await expect(wide.getByLabel("Your request")).toBeInViewport();  await wide.close();

  // 7. on a phone the draft and the conversation are tabs, and nothing scrolls sideways
  const phone = await ctx.newPage();
  await phone.setViewportSize({ width: 280, height: 640 });
  await phone.goto(ui.url());
  await expect(phone.getByRole("tab", { name: "Conversation" })).toBeVisible();
  await expect(phone.getByRole("tab", { name: "Draft" })).toBeVisible();
  expect(await phone.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(280);
  await phone.close();

  // 8. saved: the document has the text, and its history credits the person with the agent
  await ui.getByRole("button", { name: "Save to KB…" }).click();
  await ui.getByRole("button", { name: "Save", exact: true }).click();
  await expect(ui).toHaveURL(new RegExp(`/kb/doc/${doc.id}$`));
  await expect(ui.getByText("You need prod cluster access and on-call membership.")).toBeVisible();
  await expect(ui.getByText("Owner: payments team.")).toBeVisible();
  await expect(ui.getByText("Q: How do I deploy? A: Follow the steps.")).toBeVisible();
  await ui.getByRole("tab", { name: "history" }).click();
  await expect(ui.getByText(`${ADMIN.name} with ${agent.name}`)).toBeVisible();
});
