import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type BrowserContext } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { buildBinaries, mcp, onPrompt, startRunner, type RunnerHandle } from "./helpers/runner";

/**
 * End-to-end test of Plan 6, agent-to-agent questions: QAA-1 asks project QBB about its code with no runner
 * online (queued, "waiting on"), the runner starts and the fake agent answers from QBB's repository with a
 * secret in the text (scrubbed), the owner approves the draft with an edit, the answer is filed in QBB's
 * Knowledge Base and delivered to QAA-1, and a later question is answered by a human. Needs the Go toolchain
 * and git on the PATH, and a fresh stack (see README "Questions end-to-end test"). Project keys QAA and QBB.
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const OUTSIDER = { name: "Quinn Outside", email: "quinn@acme.io", password: "quinn-password-1" };
// the admin's default agent, as in the agents and workflow specs (which expect the admin to have only this one)
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;
const QUESTION = "How are orders webhooks signed?";
const TITLE = `Q1: ${QUESTION}`;
const FAKE_KEY = "AKIAABCDEFGHIJKLMNOP";

// backend/app/a2a/prompts.py ANSWER_PROMPT
const ANSWER_PROMPT = "# Answer a question from another project";

const SCENARIO = [
  onPrompt(
    ANSWER_PROMPT,
    mcp("submit_answer", {
      answer_md: `Webhooks are signed with HMAC SHA256 in \`app/sign.py\`, using key ${FAKE_KEY} from the vault.`,
      citations: [{ path: "app/sign.py", start_line: 1, end_line: 3 }],
    }),
  ),
];

type Question = {
  id: string;
  ref: string;
  status: string;
  answer_md: string | null;
  answer_source: string | null;
  redacted: boolean;
  kb_document_id: string | null;
};

async function post<T = unknown>(request: APIRequestContext, url: string, data: unknown): Promise<T> {
  const r = await request.post(url, { data, headers: WEB });
  expect(r.ok(), `${url}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return (await r.json()) as T;
}

async function get<T = unknown>(request: APIRequestContext, url: string): Promise<T> {
  const r = await request.get(url);
  expect(r.ok(), `${url}: ${r.status()}`).toBeTruthy();
  return (await r.json()) as T;
}

/** MCP tools/call with a bearer token; returns the tool's result (or throws its error text). */
async function tool<T = Record<string, unknown>>(
  request: APIRequestContext,
  token: string,
  name: string,
  args: Record<string, unknown>,
): Promise<T> {
  const r = await request.post("/api/mcp", {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json, text/event-stream", "Content-Type": "application/json" },
    data: { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args } },
  });
  expect(r.ok()).toBeTruthy();
  const result = (await r.json()).result;
  const text: string = result.content?.[0]?.text ?? "";
  if (result.isError) throw new Error(`${name}: ${text}`);
  const structured = result.structuredContent;
  return (structured ? (structured.result ?? structured) : JSON.parse(text)) as T;
}

function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", ["-c", "user.name=E2E", "-c", "user.email=e2e@acme.io", ...args], { cwd, stdio: "pipe" })
    .toString()
    .trim();
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

test("a question answered across projects", async ({ browser }) => {
  test.setTimeout(300_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-questions-"));
  leftovers.work = work;
  const bins = buildBinaries(join(work, "bin"));
  const repo = join(work, "qbb");
  mkdirSync(join(repo, "app"), { recursive: true });
  git(repo, "init", "-q");
  writeFileSync(join(repo, "app", "sign.py"), "import hmac\n\ndef sign(body, key):\n    return hmac.new(key, body, 'sha256')\n");
  git(repo, "add", ".");
  git(repo, "commit", "-q", "-m", "init");

  const ctx = await browser.newContext();
  leftovers.ctx = ctx;
  const page = await ctx.newPage();
  await setupOrSignIn(page);
  const request = page.request;

  // projects QAA (asking, with task QAA-1) and QBB (asked); the admin's agent is bound to QBB, manual mode
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Questions Team", description: "" });
  for (const key of ["QAA", "QBB"]) {
    await post(request, "/api/projects", { key, name: `Project ${key}`, description: "", team_ids: [team.id] });
    expect((await request.patch(`/api/projects/${key}`, { data: { sprints_enabled: false }, headers: WEB })).ok()).toBeTruthy();
  }
  await post(request, "/api/projects/QAA/tasks", { title: "Sync orders from QBB", type: "task" });
  type Agent = { id: string; name: string; status: string };
  const mine = await get<Agent[]>(request, "/api/agents/mine");
  const agent = mine.find((a) => a.name === AGENT_NAME) ?? (await post<Agent>(request, "/api/agents", { program: "claude_code" }));
  const manual = await request.patch(`/api/agents/${agent.id}`, { data: { answer_mode: "manual" }, headers: WEB });
  expect(manual.ok(), await manual.text()).toBeTruthy();
  // binding QBB alone replaces any binding an earlier spec left to a repository it has since deleted
  const bound = await request.put(`/api/agents/${agent.id}/bindings`, {
    data: { bindings: [{ project_ref: "QBB", local_path: repo }] },
    headers: WEB,
  });
  expect(bound.ok(), await bound.text()).toBeTruthy();
  const runnerToken = (await post<{ secret: string }>(request, "/api/tokens", { name: "Questions runner", scopes: ["runner"] })).secret;

  // 1. no runner: asked from QAA-1 in the UI, the question waits, and QAA-1 waits on QBB
  await page.goto("/projects/QAA/board?task=QAA-1");
  const drawer = page.getByRole("dialog", { name: "QAA-1" });
  await drawer.getByRole("button", { name: "Ask another project" }).click();
  await drawer.getByLabel("Project", { exact: true }).selectOption("QBB");
  await drawer.getByLabel("Question", { exact: true }).fill(QUESTION);
  await drawer.getByLabel("Context (optional)").fill("We get 401 from the webhook endpoint.");
  await drawer.getByRole("button", { name: "Check for existing answers" }).click();
  // earlier specs on this stack may have left Knowledge Base documents or memories that match some words
  await expect(drawer.getByText("No existing answers found.").or(drawer.getByText("These may already answer it:"))).toBeVisible();
  await expect(drawer.getByRole("link", { name: TITLE })).toHaveCount(0);
  await drawer.getByRole("button", { name: "Ask anyway" }).click();
  const asked = drawer.getByRole("list", { name: "Questions to other projects" });
  await expect(asked.getByText("Waiting for a runner of QBB")).toBeVisible();
  await expect(drawer.getByText("Waiting on QBB")).toBeVisible();
  const [q1] = await get<Question[]>(request, "/api/tasks/QAA-1/questions");
  expect(q1.status).toBe("queued");
  expect(q1.ref).toBe("QBB-Q1");

  // 2. the runner comes online: the agent answers, with a secret in the text; the owner approves with an edit
  leftovers.runner = startRunner({
    url: BASE,
    token: runnerToken,
    home: join(work, "home"),
    adapterOverride: bins.fakeAgent,
    scenario: SCENARIO,
    runnerBin: bins.runner,
  });
  await expect
    .poll(async () => (await get<Question>(request, `/api/questions/${q1.id}`)).status, { timeout: 60_000 })
    .toBe("draft");
  await page.goto(`/questions/${q1.id}`);
  await expect(page.getByText("Draft awaiting Root Admin's approval")).toBeVisible();
  const draft = page.getByLabel("Draft answer text");
  await expect(draft).toHaveValue(/\[redacted\]/);
  await expect(draft).not.toHaveValue(new RegExp(FAKE_KEY));
  await draft.fill(`${await draft.inputValue()} Rotate it with the ops runbook.`);
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText(`Answered by ${AGENT_NAME} (Root Admin)`)).toBeVisible();
  const answer = page.getByRole("region", { name: "Answer", exact: true });
  await expect(answer.getByText("Secrets were removed from this answer.")).toBeVisible();
  await expect(answer).toContainText("[redacted]");
  await expect(answer).toContainText("Rotate it with the ops runbook.");
  await expect(answer).not.toContainText(FAKE_KEY);
  await expect(answer.getByText("app/sign.py:1-3")).toBeVisible();

  // 3. filed in QBB's Knowledge Base under Q&A, delivered to QAA-1, and suggested when asked again
  const answered = await get<Question>(request, `/api/questions/${q1.id}`);
  expect(answered).toMatchObject({ status: "answered", answer_source: "agent", redacted: true });
  const doc = await get<{ title: string; body_md: string; path: string }>(request, `/api/kb/documents/${answered.kb_document_id}`);
  expect(doc.title).toBe(TITLE);
  expect(doc.path).toBe("Q&A");
  expect(doc.body_md).toContain("## Sources");
  expect(doc.body_md).toContain("`app/sign.py:1-3`");
  expect(doc.body_md).not.toContain(FAKE_KEY);
  await answer.getByRole("link", { name: "View in Knowledge Base" }).click();
  await expect(page.getByRole("heading", { name: TITLE })).toBeVisible();

  await page.goto("/projects/QAA/board?task=QAA-1");
  await expect(drawer.getByText("QBB answered Q1")).toBeVisible();
  await expect(drawer.getByText("Waiting on QBB")).toHaveCount(0);

  await page.goto("/questions");
  await page.getByLabel("Project", { exact: true }).selectOption("QBB");
  await page.getByLabel("Question", { exact: true }).fill(QUESTION);
  await page.getByRole("button", { name: "Check for existing answers" }).click();
  await expect(page.getByRole("list", { name: "Existing answers" }).getByRole("link", { name: TITLE })).toBeVisible();

  // 4. someone in neither project cannot see it; MCP find_answer offers the filed answer
  const invite = await post<{ invite_url: string }>(request, "/api/admin/users/invite", {
    email: OUTSIDER.email,
    name: OUTSIDER.name,
    role: "member",
  });
  const outsider = await browser.newContext({ baseURL: BASE });
  await post(outsider.request, "/api/auth/accept-invite", {
    token: invite.invite_url.split("/invite/")[1],
    password: OUTSIDER.password,
  });
  expect((await outsider.request.get(`/api/questions/${q1.id}`)).status()).toBe(404);
  await outsider.close();
  const personal = (await post<{ secret: string }>(request, "/api/tokens", { name: "Questions MCP", scopes: ["mcp"] })).secret;
  const found = await tool<{ suggestions: { kind: string; title: string }[] }>(request, personal, "find_answer", {
    project_key: "QBB",
    question: QUESTION,
  });
  expect(found.suggestions).toContainEqual(expect.objectContaining({ kind: "kb", title: TITLE }));

  // 5. with the runner gone, a new question waits; a human answers it from the Incoming tab
  await leftovers.runner.stop();
  await expect
    .poll(async () => (await get<Agent[]>(request, "/api/agents/mine")).find((a) => a.id === agent.id)?.status, {
      timeout: 30_000,
    })
    .toBe("offline");
  const second = (
    await post<{ question: Question }>(request, "/api/questions", { project_key: "QBB", body: "Which port does the sync use?" })
  ).question;
  expect(second.status).toBe("queued");
  await page.goto("/questions");
  await page.getByRole("tab", { name: "Incoming" }).click();
  await page.getByLabel("Project", { exact: true }).selectOption("QBB");
  await page.getByRole("link", { name: "Which port does the sync use?" }).click();
  await expect(page.getByText("Waiting for a runner of QBB")).toBeVisible();
  await page.getByLabel("Answer it yourself").fill("Port 8443, see `deploy/sync.yml`.");
  await page.getByRole("button", { name: "Post answer" }).click();
  await expect(page.getByText("Answered by Root Admin")).toBeVisible();
  expect(await get<Question>(request, `/api/questions/${second.id}`)).toMatchObject({ status: "answered", answer_source: "human" });
});
