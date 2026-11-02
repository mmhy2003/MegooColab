import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type BrowserContext } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { buildBinaries, mintLinkedRunnerToken, onPrompt, readReports, say, startRunner, type RunnerHandle } from "./helpers/runner";

/**
 * Plan 28: images sent with a message reach the agent as images. A chat's first message carries one, and so does a
 * task comment sent to the agent before its next run; both show with their message, full size on click, and in the
 * task's Attachments. Needs the Go toolchain and git on the PATH. Project key IMG.
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;
const SHOT = join(__dirname, "fixtures", "screenshot.png");
const BRAINSTORM = "# Brainstorm: turn the task into an approved design";

// a brainstorm run given images says so, then ends its turn
const SCENARIO = [onPrompt(BRAINSTORM, onPrompt("## Images", say("I can see the image")))];

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

test("images reach the agent from a chat and from a task", async ({ browser }) => {
  test.setTimeout(240_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-images-"));
  leftovers.work = work;
  const ctx = await browser.newContext();
  leftovers.ctx = ctx;
  const ui = await ctx.newPage();
  await setupOrSignIn(ui);
  const request = ui.request;

  const team = await post<{ id: string }>(request, "/api/teams", { name: "Image Team", description: "" });
  await post(request, "/api/projects", { key: "IMG", name: "Image Demo", description: "", team_ids: [team.id] });
  const bins = buildBinaries(join(work, "bin"));
  const repo = join(work, "repo");
  mkdirSync(repo);
  git(repo, "init", "-q");
  writeFileSync(join(repo, "README.md"), "# checkout\n");
  git(repo, "add", ".");
  git(repo, "commit", "-q", "-m", "init");
  type Agent = { id: string; name: string; status: string };
  const mine = await get<Agent[]>(request, "/api/agents/mine");
  const agent = mine.find((a) => a.name === AGENT_NAME) ?? (await post<Agent>(request, "/api/agents", { program: "claude_code" }));
  const bound = await request.put(`/api/agents/${agent.id}/bindings`, {
    data: { bindings: [{ project_ref: "IMG", local_path: repo }] },
    headers: WEB,
  });
  expect(bound.ok(), await bound.text()).toBeTruthy();
  const token = await mintLinkedRunnerToken(request, agent.id, "Images");
  const reports = join(work, "reports");
  leftovers.runner = startRunner({
    url: BASE, token, home: join(work, "home"), adapterOverride: bins.fakeAgent, scenario: SCENARIO, runnerBin: bins.runner,
    env: { FAKEAGENT_IMAGES: "1", FAKEAGENT_REPORT_DIR: reports },
  });
  await expect
    .poll(async () => (await get<Agent[]>(request, "/api/agents/mine")).find((a) => a.id === agent.id)?.status, { timeout: 20_000 })
    .toBe("online");
  const imagesSeen = () => readReports(reports).flatMap((r) => r.images ?? []);

  // 1. a chat whose first message carries a screenshot
  await ui.goto("/projects/IMG/chats");
  await ui.getByRole("button", { name: "New chat" }).click();
  const dialog = ui.getByRole("dialog", { name: "New chat" });
  await dialog.getByLabel("Message").fill("The checkout button is cut off, see this");
  await dialog.locator('input[type="file"]').setInputFiles(SHOT);
  await expect(dialog.getByRole("button", { name: "Remove screenshot.png" })).toBeVisible();
  await dialog.getByRole("button", { name: "Start chat" }).click();
  await expect(ui).toHaveURL(/\/chats\/[0-9a-f-]{36}$/);
  const view = ui.getByRole("main");
  await expect(view.getByText("I can see the image").first()).toBeVisible({ timeout: 30_000 });
  await expect.poll(() => imagesSeen().length, { timeout: 15_000 }).toBeGreaterThan(0);
  expect(imagesSeen()[0]).toMatchObject({ mime: "image/png", where: "prompt" });

  // it shows with the chat's first message, full size on click
  await view.getByRole("button", { name: "Open screenshot.png" }).click();
  const viewer = ui.getByRole("dialog", { name: "screenshot.png" });
  await expect(viewer.getByRole("link", { name: "Download" })).toBeVisible();
  await ui.keyboard.press("Escape");
  await expect(viewer).toBeHidden();

  // 2. a task's comment to the agent, sent before its run, goes with that run's start
  await post(request, "/api/projects/IMG/tasks", { title: "Fix the button", type: "task", assignee_agent_id: agent.id });
  const key = (await get<{ key: string; title: string }[]>(request, "/api/projects/IMG/tasks")).find((t) => t.title === "Fix the button")!.key;
  await ui.goto(`/projects/IMG/tasks/${key.split("-")[1]}`);
  const box = ui.getByRole("textbox", { name: "Add a comment" });
  await ui.getByRole("switch", { name: `Send to ${AGENT_NAME}` }).click();
  await box.fill("Make it full width, like this");
  await ui.locator('form input[type="file"]').setInputFiles(SHOT);
  await expect(ui.getByRole("button", { name: "Remove screenshot.png" })).toBeVisible();
  await ui.getByRole("button", { name: "Send to agent" }).click();
  await expect(ui.getByRole("button", { name: "Open screenshot.png" })).toBeVisible();
  const before = imagesSeen().length;
  await post(request, `/api/tasks/${key}/workflow/start`, {});
  await expect.poll(() => imagesSeen().length, { timeout: 30_000 }).toBeGreaterThan(before);

  // and it is one of the task's Attachments, from that message
  const attachments = ui.locator("section", { has: ui.getByRole("heading", { name: "Attachments" }) });
  await expect(attachments.getByRole("img", { name: "screenshot.png" })).toBeVisible();
  await expect(attachments.getByRole("link", { name: `${ADMIN.name}'s message` })).toHaveAttribute("href", /^#activity-/);
});
