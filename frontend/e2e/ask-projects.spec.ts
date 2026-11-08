import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type BrowserContext } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { buildBinaries, mcp, mintLinkedRunnerToken, onPrompt, say, startRunner, type RunnerHandle } from "./helpers/runner";

/**
 * Agents asking other projects on their own: a freestyle chat on ASK names project ANS; its agent, told in its prompt
 * which projects it may ask (ANS marked as mentioned), asks ANS with wait; the chat waits ("waiting for ANS's
 * answer", the banner), ANS's agent answers, and the chat's agent picks up again by itself and replies with the
 * answer. A second question that isn't answered in time: the person chooses "Go on without it" and the agent
 * carries on. Needs the Go toolchain and git on the PATH, and a fresh stack (README "Agents end-to-end test").
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;
// backend/app/a2a/prompts.py ANSWER_PROMPT, app/a2a/context.py ASK_SECTION, app/workflow/context.py
const ANSWER_PROMPT = "# Answer a question from another project";
const ASK_SECTION = "## Other projects you can ask";
const MENTIONED = "← mentioned in this chat";

// A turn may start afresh with the whole conversation in its prompt, so each step keys on what only its own turn has:
// how many questions are still left, the resume text's first line, or the line for an answer that didn't come.
const SCENARIO = [
  // the chat's first turn (no question asked yet): it asks only if its prompt lists ANS as mentioned
  onPrompt("Integrate the ANS signing", onPrompt("20 are left.", onPrompt(ASK_SECTION, onPrompt(MENTIONED,
    mcp("ask_project", { project_key: "ANS", question: "Which header carries the webhook signature?", wait: true }),
    say("I asked ANS which header carries the signature; waiting for their answer."),
  )))),
  // picked up again with the answer
  onPrompt("Answers from other projects arrived.", onPrompt("X-Signature header",
    say("Using ANS's HMAC signing from the X-Signature header."))),
  // the second message (one question asked so far): another question it waits for
  onPrompt("And the clock skew?", onPrompt("19 are left.",
    mcp("ask_project", { project_key: "ANS", question: "Which clock skew does it allow?", wait: true }),
    say("Asked ANS about the clock skew; waiting."),
  )),
  onPrompt("wasn't answered", say("Carrying on without the clock skew answer.")),
  // ANS's answering sessions: the first answers after a pause, the second never in time
  onPrompt(ANSWER_PROMPT, onPrompt("webhook signature",
    { sleep_ms: 8_000 },
    mcp("submit_answer", {
      answer_md: "Signed with HMAC SHA256 and sent in the X-Signature header (`app/sign.py`).",
      citations: [{ path: "app/sign.py", start_line: 1, end_line: 3 }],
    }),
  )),
  onPrompt(ANSWER_PROMPT, onPrompt("clock skew", { sleep_ms: 120_000 })),
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

function repoAt(dir: string, files: Record<string, string>): string {
  mkdirSync(dir, { recursive: true });
  git(dir, "init", "-q");
  for (const [path, body] of Object.entries(files)) {
    mkdirSync(join(dir, path, ".."), { recursive: true });
    writeFileSync(join(dir, path), body);
  }
  git(dir, "add", ".");
  git(dir, "commit", "-q", "-m", "init");
  return dir;
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

test("a chat asks another project, waits, and picks up again by itself", async ({ browser }) => {
  test.setTimeout(300_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-ask-"));
  leftovers.work = work;
  const bins = buildBinaries(join(work, "bin"));
  const askRepo = repoAt(join(work, "ask"), { "README.md": "# ask\n" });
  const ansRepo = repoAt(join(work, "ans"), { "app/sign.py": "import hmac\n\ndef sign(body, key):\n    return hmac.new(key, body, 'sha256')\n" });

  const ctx = await browser.newContext();
  leftovers.ctx = ctx;
  const ui = await ctx.newPage();
  await setupOrSignIn(ui);
  const request = ui.request;

  // ASK (the chat's project) and ANS (asked); the admin's agent works on both, answers on its own, and runs three
  // sessions at once (the chat's turn and ANS's answering sessions)
  const me = (await get<{ user: { id: string } }>(request, "/api/auth/me")).user.id;
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Ask Team", description: "" });
  expect((await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB })).ok()).toBeTruthy();
  await post(request, "/api/projects", { key: "ASK", name: "Asking app", description: "", team_ids: [team.id] });
  await post(request, "/api/projects", {
    key: "ANS", name: "Answers", description: "Webhooks and their signing", team_ids: [team.id],
  });
  type Agent = { id: string; name: string; status: string };
  const mine = await get<Agent[]>(request, "/api/agents/mine");
  const agent = mine.find((a) => a.name === AGENT_NAME) ?? (await post<Agent>(request, "/api/agents", { program: "claude_code" }));
  const set = await request.patch(`/api/agents/${agent.id}`, {
    data: { answer_mode: "auto", max_concurrent_runs: 3 }, headers: WEB,
  });
  expect(set.ok(), await set.text()).toBeTruthy();
  const bound = await request.put(`/api/agents/${agent.id}/bindings`, {
    data: { bindings: [{ project_ref: "ASK", local_path: askRepo }, { project_ref: "ANS", local_path: ansRepo }] },
    headers: WEB,
  });
  expect(bound.ok(), await bound.text()).toBeTruthy();
  const token = await mintLinkedRunnerToken(request, agent.id, "Ask runner");
  leftovers.runner = startRunner({
    url: BASE, token, home: join(work, "home"), adapterOverride: bins.fakeAgent, scenario: SCENARIO, runnerBin: bins.runner,
  });
  await expect
    .poll(async () => (await get<Agent[]>(request, "/api/agents/mine")).find((a) => a.id === agent.id)?.status, { timeout: 20_000 })
    .toBe("online");

  // 1. a freestyle chat names ANS: its agent asks ANS and waits
  const chat = await post<{ id: string }>(request, "/api/chats", {
    project_key: "ASK", agent_id: agent.id, mode: "freestyle",
    message: "Integrate the ANS signing into our webhook client",
  });
  await ui.goto(`/chats/${chat.id}`);
  const view = ui.getByRole("main");
  const banner = view.locator("[data-project-waits]");
  await expect(banner.getByText("Waiting for ANS's answer (ANS-Q1)")).toBeVisible({ timeout: 60_000 });
  await expect(banner.getByText(/picks up again on its own when the answer arrives/)).toBeVisible();
  await expect(view.locator("header").getByText("waiting for ANS's answer")).toBeVisible();
  await expect(view.getByText("asked ANS a question (Q1)")).toBeVisible();

  // 2. ANS answers; the agent picks up again by itself, with no message from the person
  await expect(view.getByText("Using ANS's HMAC signing from the X-Signature header.")).toBeVisible({ timeout: 60_000 });
  await expect(banner).toHaveCount(0);
  await expect(view.getByText("ANS answered Q1")).toBeVisible();

  // 3. a second question that isn't answered in time: Go on without it
  await view.locator("[data-chat]").getByText("waiting for your reply", { exact: true }).waitFor({ timeout: 30_000 });
  const box = view.getByRole("textbox", { name: `Message ${AGENT_NAME}` });
  await box.fill("And the clock skew?");
  await view.getByRole("button", { name: "Send", exact: true }).click();
  await expect(banner.getByText("Waiting for ANS's answer (ANS-Q2)")).toBeVisible({ timeout: 60_000 });
  await banner.getByRole("button", { name: "Go on without it" }).click();
  await expect(view.getByText("Carrying on without the clock skew answer.")).toBeVisible({ timeout: 60_000 });
  await expect(banner).toHaveCount(0);
  type Question = { ref: string; status: string };
  const asked = await get<Question[]>(request, `/api/questions?box=mine&project=ANS`);
  expect(asked.find((q) => q.ref === "ANS-Q2")?.status).not.toBe("withdrawn"); // still open, as an ordinary question
});
