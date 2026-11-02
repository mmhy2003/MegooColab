import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type BrowserContext } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { buildBinaries, mcp, mintLinkedRunnerToken, onPrompt, say, startRunner, type RunnerHandle } from "./helpers/runner";

/**
 * Plan 21: a chat with an agent on project CHT goes through the task workflow as a conversation: a typed reply answers
 * its question, another asks for changes to its plan, the build finishes, the round goes on the board, a second round
 * starts, and the chat ends. Needs the Go toolchain and git on the PATH.
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;
const R1 = "CHT-1";
const BRAINSTORM = "# Brainstorm: turn the task into an approved design";
const PLAN = "# Plan: break the approved design into steps";
const IMPLEMENT = "# Build: implement one plan step";
const STEP_REVIEW = "# Build: review one implemented step";
const FINAL_REVIEW = "# Review: final review of the whole change";
const FINISH = "# Finish: verify and integrate the finished work";
const PR_URL = "https://git.example.com/cht/pull/7";

const SCENARIO = [
  onPrompt(
    `## Task ${R1}\n`,
    onPrompt(
      BRAINSTORM,
      onPrompt("Postgres", mcp("submit_design", { key: R1, markdown: "# Empty email\n\nShow an error under the field." })),
      // only the first turn asks: the answered one (its thread holds the question) submits the design
      onPrompt("(no thread items)", mcp("ask_human", { key: R1, question: "Which database does the login use?", choices: [] })),
    ),
    onPrompt(
      PLAN,
      mcp("submit_plan", { key: R1, markdown: "# Plan\n\nDo it all at once.", steps: [{ title: "Do it all", detail: "Everything." }] }),
      // asked for changes: the last version submitted is the split one
      onPrompt("Split", mcp("submit_plan", { key: R1, markdown: "# Plan\n\n1. Validate the email", steps: [{ title: "Validate the email", detail: "One check." }] })),
    ),
    onPrompt(
      IMPLEMENT,
      { write: { path: "email.txt", content: "validated\n" } },
      { commit: { message: "feat: validate the email", all: true } },
      mcp("complete_step", { key: R1, step: 1, summary: "Validated", tests_passed: true }),
    ),
    onPrompt(STEP_REVIEW, mcp("submit_review", { key: R1, verdict: "approved", findings: [] })),
    onPrompt(FINAL_REVIEW, mcp("submit_review", { key: R1, verdict: "approved", findings: [] })),
    onPrompt(FINISH, mcp("report_finish", { key: R1, outcome: "pr_opened", branch: "megoo/CHT-1-fix", pr_url: PR_URL, tests_passed: true })),
  ),
  // round 2 (its key comes after round 1's step card): what came before is in its prompt
  onPrompt("## Earlier rounds of this chat", onPrompt(BRAINSTORM, say("Looking at the retries"), { sleep_ms: 60_000 })),
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

test("a chat with an agent, from first message to the board and a second round", async ({ browser }) => {
  test.setTimeout(300_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-chats-"));
  leftovers.work = work;
  const ctx = await browser.newContext();
  leftovers.ctx = ctx;
  const ui = await ctx.newPage();
  await setupOrSignIn(ui);
  const request = ui.request;

  const me = (await get<{ user: { id: string } }>(request, "/api/auth/me")).user.id;
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Chat Team", description: "" });
  // a member of the project's team, so the dashboard's My teams scope covers it
  expect((await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB })).ok()).toBeTruthy();
  await post(request, "/api/projects", { key: "CHT", name: "Chat Demo", description: "", team_ids: [team.id] });
  const bins = buildBinaries(join(work, "bin"));
  const repo = join(work, "repo");
  mkdirSync(repo);
  git(repo, "init", "-q");
  writeFileSync(join(repo, "README.md"), "# login\n");
  git(repo, "add", ".");
  git(repo, "commit", "-q", "-m", "init");
  type Agent = { id: string; name: string; status: string };
  const mine = await get<Agent[]>(request, "/api/agents/mine");
  const agent = mine.find((a) => a.name === AGENT_NAME) ?? (await post<Agent>(request, "/api/agents", { program: "claude_code" }));
  const bound = await request.put(`/api/agents/${agent.id}/bindings`, {
    data: { bindings: [{ project_ref: "CHT", local_path: repo }] },
    headers: WEB,
  });
  expect(bound.ok(), await bound.text()).toBeTruthy();
  const token = await mintLinkedRunnerToken(request, agent.id, "Chats");
  leftovers.runner = startRunner({
    url: BASE, token, home: join(work, "home"), adapterOverride: bins.fakeAgent, scenario: SCENARIO, runnerBin: bins.runner,
  });
  await expect
    .poll(async () => (await get<Agent[]>(request, "/api/agents/mine")).find((a) => a.id === agent.id)?.status, { timeout: 20_000 })
    .toBe("online");

  // 1. a new chat from the project's Chats tab: the project is set, any free agent
  await ui.goto("/projects/CHT/chats");
  await ui.getByRole("button", { name: "New chat" }).click();
  await ui.getByLabel("Message").fill("Fix the empty email crash");
  await ui.getByRole("button", { name: "Start chat" }).click();
  await expect(ui).toHaveURL(/\/chats\/[0-9a-f-]{36}$/);
  const view = ui.getByRole("main");
  await expect(view.getByText("Which database does the login use?")).toBeVisible({ timeout: 30_000 });
  // the question waits on the viewer: the corner button and the state in the header both go to it
  await expect(view.getByRole("button", { name: "1 waiting on you" })).toBeVisible();
  await expect(view.getByRole("button", { name: "waiting: answer the agent's question" })).toBeVisible();

  // 2. the dashboard shows the chat waiting
  const chatUrl = ui.url();
  await ui.goto("/");
  await expect(ui.getByRole("group", { name: "Open chats" })).toBeVisible();
  await expect(ui.getByRole("region", { name: "Chats" }).getByText("Fix the empty email crash")).toBeVisible();
  await ui.goto(chatUrl);

  // 3. typing answers the question
  const box = view.getByRole("textbox", { name: `Message ${AGENT_NAME}` });
  await expect(view.getByText(`Your message answers ${AGENT_NAME}'s question.`)).toBeVisible();
  await box.fill("Postgres");
  await view.getByRole("button", { name: "Send", exact: true }).click();

  // 4. the design arrives: approve it; then the plan: ask for changes by typing
  const design = view.getByRole("region", { name: "Design" });
  await expect(design.getByRole("button", { name: "Approve" })).toBeVisible({ timeout: 30_000 });
  await expect(view.getByText(`Your message asks ${AGENT_NAME} to change the design. Approve stays on the card.`)).toBeVisible({ timeout: 30_000 });
  await design.getByRole("button", { name: "Approve" }).click();
  const plan = view.getByRole("region", { name: "Plan" });
  await expect(plan.getByRole("button", { name: "Approve" })).toBeVisible({ timeout: 30_000 });
  await expect(view.getByText(`Your message asks ${AGENT_NAME} to change the plan. Approve stays on the card.`)).toBeVisible();
  await box.fill("Split it into one clear step");
  await view.getByRole("button", { name: "Send", exact: true }).click();
  await expect(plan.getByText("Validate the email").first()).toBeVisible({ timeout: 30_000 });
  // the plan session submits, then ends its run: the plan waits for approval only then
  await expect(view.getByText(`Your message asks ${AGENT_NAME} to change the plan. Approve stays on the card.`)).toBeVisible({ timeout: 30_000 });
  await plan.getByRole("button", { name: "Approve" }).click();

  // 5. the build runs to the end; the round is offered to the board
  const dialog = ui.getByRole("dialog", { name: "Add this to the board?" });
  await expect(dialog).toBeVisible({ timeout: 90_000 });
  await expect(dialog.getByLabel("Title")).toHaveValue("Fix the empty email crash");
  await dialog.getByRole("button", { name: "Create task" }).click();
  await expect(dialog).toBeHidden();
  const board = await get<{ key: string; column_category: string }[]>(request, "/api/projects/CHT/tasks");
  expect(board.find((t) => t.key === R1)?.column_category).toBe("done");
  expect(board.filter((t) => t.key !== R1)).toHaveLength(1); // its one step, as a subtask

  // 6. another message starts round 2
  await expect(view.getByText("Starts a new round: the agent talks it through, then design, plan, build and finish again.")).toBeVisible();
  await box.fill("Also add retries to the payment API");
  await view.getByRole("button", { name: "Send", exact: true }).click();
  await expect(view.getByText(/Round 2 · Also add retries/)).toBeVisible({ timeout: 15_000 });
  await expect(view.getByText("Looking at the retries")).toBeVisible({ timeout: 30_000 });

  // the page stays put on a short window: the chat list and the conversation scroll on their own, the chat's
  // header and message box stay in view, and the conversation opened at the latest
  await ui.setViewportSize({ width: 1280, height: 600 });
  const thread = view.locator("[data-thread]");
  await expect.poll(() => thread.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true);
  expect(await ui.evaluate(() => document.documentElement.scrollHeight <= document.documentElement.clientHeight + 1)).toBe(true);
  await thread.evaluate((el) => el.scrollTo({ top: 0, behavior: "instant" }));
  await expect(view.getByRole("button", { name: /^Go to the latest and follow/ })).toBeVisible();
  await expect(view.getByRole("heading", { level: 2 })).toBeInViewport();
  await expect(box).toBeInViewport();
  await view.getByRole("button", { name: /^Go to the latest and follow/ }).click();
  await expect(view.getByText("Following live")).toBeVisible();
  await expect(view.getByText("Looking at the retries")).toBeInViewport();

  // 7. end it, and leave round 2 off the board
  await view.getByRole("button", { name: "End chat" }).click();
  const confirm = ui.getByRole("alertdialog");
  if (await confirm.isVisible().catch(() => false)) await confirm.getByRole("button", { name: "End chat" }).click();
  await ui.getByRole("dialog", { name: "Add this to the board?" }).getByRole("button", { name: "No, just end it" }).click();
  await expect(ui.getByRole("dialog", { name: "Add this to the board?" })).toBeHidden(); // the decision is saved
  await expect(view.getByText("This chat has ended.")).toBeVisible();
  const chatId = ui.url().split("/").pop()!;
  const r2 = (await get<{ rounds: { key: string; board: string | null }[] }>(request, `/api/chats/${chatId}`)).rounds[1];
  expect(r2.board).toBe("declined");
  expect((await get<{ key: string }[]>(request, "/api/projects/CHT/tasks")).some((t) => t.key === r2.key)).toBe(false);
});
