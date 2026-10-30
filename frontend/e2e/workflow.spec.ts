import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { pickAssignee } from "./helpers/assignee";
import {
  buildBinaries,
  mcp,
  onPrompt,
  readReports,
  say,
  startRunner,
  type FakeAgentReport,
  type RunnerHandle,
} from "./helpers/runner";

/**
 * End-to-end test of Plan 3: a task goes from To Do to Done through the workflow, driven by the fake agent
 * over the real stack (UI, server, runner, agent, MCP). Needs the Go toolchain and git on the PATH, and a
 * fresh stack (see README "Workflow end-to-end test").
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;
const KEY = "WFL-1";
const PROBE_KEY = "WFL-4"; // after WFL-1's plan subtasks, WFL-2 and WFL-3
const PR_URL = "https://example.test/pr/1";
const BRANCH = "megoo/WFL-1-add-a-greeting";

// What each run's prompt starts with or contains (backend/app/workflow/methodology_texts and context.py).
const BRAINSTORM = "# Brainstorm: turn the task into an approved design";
const ANSWERED = "The human answered your question.";
const PLAN = "# Plan: break the approved design into steps";
const PLAN_REJECTED = "Revise and resubmit with submit_plan.";
const IMPLEMENT = "# Build: implement one plan step";
const STEP_REVIEW = "# Build: review one implemented step";
const FIX = "Review findings to address:";
const RE_REVIEW = "## Previous review findings";
const FINAL_REVIEW = "# Review: final review of the whole change";
const FINISH = "# Finish: verify and integrate the finished work";
const STEP = (n: number) => `## Step ${n} of 2`;

const GOOD_MOCKUP = `<!doctype html><html><body style="font-family:sans-serif">
<h1>Greeting styles</h1>
<button id="friendly" data-megoo-choice="a" style="font-size:24px">Hi there!</button>
<p>Formal: Good day.</p>
</body></html>`;

// Tries everything a mockup must not be able to do, and writes what happened into its own DOM.
const PROBE_MOCKUP = `<!doctype html><html><body>
<div id="probe">probing</div>
<button id="undeclared" data-megoo-choice="zzz">Undeclared choice</button>
<button id="declared" data-megoo-choice="a">Declared choice</button>
<script>
var probe = document.getElementById("probe");
function mark(k, v) { probe.setAttribute("data-" + k, String(v)); }
document.addEventListener("securitypolicyviolation", function (e) { mark("csp", e.effectiveDirective || e.violatedDirective); });
var pending = 2;
function done() { if (--pending === 0) mark("done", "1"); }
function probeFetch(name, url) {
  try {
    fetch(url, { credentials: "include" })
      .then(function (r) { return r.text().then(function (t) { mark(name, "LEAKED " + r.status + " " + t.slice(0, 80)); }); })
      .catch(function (e) { mark(name, "blocked " + e.name); })
      .then(done);
  } catch (e) { mark(name, "blocked " + e.name); done(); }
}
probeFetch("fetch-relative", "/api/auth/me");
probeFetch("fetch-absolute", "${BASE}/api/auth/me");
try { mark("cookie", "LEAKED " + JSON.stringify(document.cookie)); } catch (e) { mark("cookie", "blocked " + e.name); }
try { top.location = "/"; mark("top", "attempted"); } catch (e) { mark("top", "blocked " + e.name); }
parent.postMessage({ type: "megoo-choice", choice: "zzz" }, "*");
mark("posted", "zzz");
</script>
</body></html>`;

const SCENARIO = [
  onPrompt(
    BRAINSTORM,
    onPrompt(
      `## Task ${KEY}`,
      mcp("ask_human", {
        key: KEY,
        question: "Which greeting style should the app use?",
        choices: [
          { id: "a", label: "Friendly", description: "Hi there!", recommended: true },
          { id: "b", label: "Formal", description: "Good day." },
        ],
        mockup_html: GOOD_MOCKUP,
        mockup_title: "Greeting styles",
        mockup_choices: ["a"],
      }),
    ),
    onPrompt(
      `## Task ${PROBE_KEY}`,
      mcp("ask_human", {
        key: PROBE_KEY,
        question: "Does this probe look right?",
        choices: [
          { id: "a", label: "Yes" },
          { id: "b", label: "No" },
        ],
        mockup_html: PROBE_MOCKUP,
        mockup_title: "Sandbox probe",
        mockup_choices: ["a"],
      }),
    ),
  ),
  onPrompt(ANSWERED, mcp("submit_design", { key: KEY, markdown: "# Greeting design\n\nGreet people with a friendly Hi there!" })),
  onPrompt(
    PLAN,
    mcp("submit_plan", {
      key: KEY,
      markdown: "# Greeting plan v1\n\nOne pass.",
      steps: [
        { title: "Write the greeting", detail: "Add step1.txt with the greeting." },
        { title: "Wire it up", detail: "Add step2.txt that uses it." },
      ],
    }),
  ),
  onPrompt(
    PLAN_REJECTED,
    mcp("submit_plan", {
      key: KEY,
      markdown: "# Greeting plan v2\n\nWith the tests split out.",
      steps: [
        { title: "Write the greeting", detail: "Add step1.txt with the greeting, and its test." },
        { title: "Wire it up", detail: "Add step2.txt that uses it, and its test." },
      ],
    }),
  ),
  onPrompt(
    IMPLEMENT,
    onPrompt(
      STEP(1),
      { sleep_ms: 4_000 }, // holds Build at "1 of 2 steps" for the test to see
      { report_file: { path: ".megoocolab/plan.md" } },
      { report_file: { path: ".megoocolab/design.md" } },
      { write: { path: "step1.txt", content: "Hi there!\n" } },
      { commit: { message: "step 1: the greeting", all: true } },
      mcp("complete_step", { key: KEY, step: 1, summary: "Greeting written", tests_passed: true, test_command: "make test" }),
      say("Step 1 is done"), // the run's summary
    ),
    onPrompt(
      STEP(2),
      { sleep_ms: 8_000 }, // the test stops the runner here
      { write: { path: "step2.txt", content: "uses step1\n" } },
      { commit: { message: "step 2: wire it up", all: true } },
      mcp("complete_step", { key: KEY, step: 2, summary: "Wired up", tests_passed: true }),
    ),
  ),
  onPrompt(
    FIX,
    { write: { path: "step1.txt", content: "Hi there, and bye!\n" } },
    { commit: { message: "step 1: address review", all: true } },
    mcp("complete_step", { key: KEY, step: 1, summary: "Added the farewell", tests_passed: true }),
  ),
  onPrompt(
    STEP_REVIEW,
    // a re-review approves; its prompt also holds "## Step 1 of 2", so the changes_requested call below then
    // gets 409 already_submitted (one verdict per review run), which the test checks
    onPrompt(RE_REVIEW, mcp("submit_review", { key: KEY, verdict: "approved", findings: [] })),
    onPrompt(STEP(2), mcp("submit_review", { key: KEY, verdict: "approved", findings: [] })),
    onPrompt(
      STEP(1),
      mcp("submit_review", {
        key: KEY,
        verdict: "changes_requested",
        findings: [{ severity: "important", file: "step1.txt", line: 1, summary: "The greeting has no farewell" }],
      }),
    ),
  ),
  onPrompt(FINAL_REVIEW, { sleep_ms: 5_000 }, mcp("submit_review", { key: KEY, verdict: "approved", findings: [] })),
  onPrompt(
    FINISH,
    mcp("report_finish", { key: KEY, outcome: "pr_opened", branch: BRANCH, pr_url: PR_URL, tests_passed: true }),
  ),
];

type Run = { id: string; workflow_role: string | null; step: number | null; status: string; reason: string | null };
type ActivityItem = { type: string; kind?: string; question?: { id: string; status: string; answer_choice: string | null } };

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

function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", ["-c", "user.name=E2E", "-c", "user.email=e2e@acme.io", ...args], { cwd, stdio: "pipe" })
    .toString()
    .trim();
}

function column(page: Page, name: string) {
  return page.getByRole("region", { name: `${name} column` });
}

async function drag(page: Page, cardName: RegExp, from: string, to: string) {
  const card = column(page, from).getByRole("button", { name: cardName });
  const a = (await card.boundingBox())!;
  const b = (await column(page, to).boundingBox())!;
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(a.x + a.width / 2 + 20, a.y + a.height / 2, { steps: 5 });
  await page.mouse.move(b.x + b.width / 2, b.y + 120, { steps: 15 });
  await page.mouse.up();
}

async function runs(page: Page, key: string): Promise<Run[]> {
  const res = await page.request.get(`/api/tasks/${key}/agent-runs`);
  expect(res.ok()).toBeTruthy();
  return ((await res.json()) as Run[]).reverse(); // oldest first
}

const runLabel = (r: Run) => `${r.workflow_role}${r.step ? `:${r.step}` : ""} ${r.status}${r.reason ? ` (${r.reason})` : ""}`;

/** The one report whose run's prompt contains every one of `texts`. */
function reportFor(dir: string, ...texts: string[]): FakeAgentReport {
  const found = readReports(dir).filter((r) => (r.prompts ?? []).some((p) => texts.every((t) => p.includes(t))));
  expect(found, `reports for ${texts.join(" + ")}`).toHaveLength(1);
  return found[0];
}

test("workflow end to end", async ({ browser }) => {
  test.setTimeout(420_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-workflow-"));
  leftovers.work = work;
  const bins = buildBinaries(join(work, "bin"));
  const repo = join(work, "repo");
  mkdirSync(repo);
  git(repo, "init", "-q");
  writeFileSync(join(repo, "README.md"), "# greeter\n");
  git(repo, "add", ".");
  git(repo, "commit", "-q", "-m", "init");
  const repoHead = git(repo, "rev-parse", "HEAD");
  const repoBranch = git(repo, "rev-parse", "--abbrev-ref", "HEAD");
  const home = join(work, "home");
  const reports = join(work, "reports");
  const launch = (token: string) => {
    leftovers.runner = startRunner({
      url: BASE,
      token,
      home,
      adapterOverride: bins.fakeAgent,
      scenario: SCENARIO,
      runnerBin: bins.runner,
      env: { FAKEAGENT_SESSIONS_DIR: join(work, "sessions"), FAKEAGENT_RESUME: "1", FAKEAGENT_REPORT_DIR: reports },
    });
  };

  const ctx = await browser.newContext();
  leftovers.ctx = ctx;
  const page = await ctx.newPage();
  // everything the browser logs, from every frame (the mockup's CSP violations included)
  const consoleLines: string[] = [];
  page.on("console", (msg) => consoleLines.push(`${msg.type()} @${msg.location().url}: ${msg.text()}`));

  // 1. project WFL, a token, the agent bound to the temp repo, the runner with the scenario
  await setupOrSignIn(page);
  await page.goto("/teams");
  await page.getByRole("button", { name: "New team" }).click();
  await page.getByLabel("Name").fill("Workflow Team");
  await page.getByRole("button", { name: "Create team" }).click();
  await expect(page.getByRole("heading", { name: "Workflow Team" })).toBeVisible();
  await page.getByRole("button", { name: "Edit members" }).click();
  await page.getByRole("option", { name: new RegExp(ADMIN.name) }).click(); // tick them in the member list
  await page.getByRole("button", { name: "Save members" }).click();

  await page.goto("/projects/new");
  await page.getByLabel("Name").fill("Workflow Demo");
  await page.getByLabel(/^Key/).fill("WFL");
  await page.getByLabel("Workflow Team").check();
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page).toHaveURL(/\/projects\/WFL\/board/);
  const patched = await page.request.patch("/api/projects/WFL", {
    data: { sprints_enabled: false },
    headers: { "X-Megoo-Client": "web" },
  });
  expect(patched.ok()).toBeTruthy();

  await page.goto("/settings/tokens");
  await page.getByRole("button", { name: "New token" }).click();
  await page.getByLabel("Name").fill("Workflow runner");
  await page.getByRole("checkbox", { name: "Runner" }).check();
  await page.getByRole("button", { name: "Create token" }).click();
  const token = await page.getByLabel("Your token").inputValue();
  await page.getByRole("button", { name: "Done" }).click();

  await page.goto("/settings/agents");
  const agentHeading = page.getByRole("heading", { name: AGENT_NAME });
  await expect(page.getByRole("button", { name: "Add project" }).or(page.getByText("No agents yet."))).toBeVisible();
  if (!(await agentHeading.isVisible())) {
    await page.getByRole("button", { name: "Add agent" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Add agent" }).click();
    await expect(agentHeading).toBeVisible();
  }
  // The agents spec, when it ran first on this stack, added the agent with a binding to a repository it has
  // since deleted. The runner reports an agent with any broken binding as unavailable, so bind WFL alone.
  while ((await page.getByRole("button", { name: /^Remove row / }).count()) > 0) {
    await page.getByRole("button", { name: /^Remove row / }).first().click();
  }
  await page.getByRole("button", { name: "Add project" }).click();
  await page.getByLabel("Project").selectOption("WFL");
  await page.getByLabel("Local path").fill(repo);
  await page.getByRole("button", { name: "Save bindings" }).click();
  await expect(page.getByLabel("Local path")).toHaveValue(repo);
  // the agent runs on the machine of the token it is linked to
  await page.getByLabel("Machine").selectOption({ label: "Workflow runner" });
  await expect(page.getByText("on Workflow runner")).toBeVisible();
  launch(token);
  await expect(page.getByText("Online")).toBeVisible({ timeout: 10_000 });
  const agentId: string = (await (await page.request.get("/api/agents/mine")).json())[0].id;
  const worktree = join(home, "cache", "megoocolab", "worktrees", agentId, KEY);

  // 2. a task assigned to the agent, dragged to In Progress: the workflow starts in Brainstorm
  await page.goto("/projects/WFL/board");
  await page.getByLabel("New task in To Do").fill("Add a greeting");
  await page.getByLabel("New task in To Do").press("Enter");
  await expect(column(page, "To Do").getByText("Add a greeting")).toBeVisible();
  await page.goto(`/projects/WFL/board?task=${KEY}`);
  const drawer = page.getByRole("dialog", { name: KEY });
  await pickAssignee(drawer, AGENT_NAME);
  await expect(drawer.getByText(`assigned this to ${AGENT_NAME}`)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await drag(page, /WFL-1 Add a greeting/, "To Do", "In Progress");
  const card = column(page, "In Progress").getByRole("button", { name: /WFL-1 Add a greeting/ });
  await expect(card).toBeVisible();
  await expect(card.getByRole("group", { name: "Stage: Brainstorm (1 of 6)" })).toBeVisible();

  // 3. the question: 2 choice buttons and the mockup; the mockup's choice preselects, "Send answer" answers
  await card.click();
  await expect(drawer).toBeVisible();
  const panel = drawer.getByRole("region", { name: "Workflow" });
  await expect(drawer.getByText("Which greeting style should the app use?")).toBeVisible({ timeout: 30_000 });
  const friendly = drawer.getByRole("button", { name: /^Friendly/ });
  // exactly the agent's 2 choices (recommended first), plus MegooColab's own "Other"
  const question = drawer.getByRole("listitem").filter({ has: page.getByText("Which greeting style should the app use?") });
  await expect(question.getByRole("list").getByRole("button")).toHaveText([/^Friendly/, /^Formal/, "Other"]);
  // the question's own frame: the Mockups panel shows the same version without clickable choices
  const mockup = question.frameLocator('iframe[title="Mockup v1: Greeting styles"]');
  await mockup.locator('[data-megoo-choice="a"]').click();
  await expect(friendly).toHaveAttribute("aria-pressed", "true");
  await drawer.getByRole("button", { name: "Send answer" }).click();
  await expect(drawer.getByText(`${ADMIN.name} answered:`)).toBeVisible();
  await expect(drawer.getByText(/answered: Friendly/)).toBeVisible();

  // 4. the design; NEEDS YOU on the card; the answer resumed the brainstorm session
  const designSection = drawer.locator("#document-design");
  await expect(designSection.getByText("Greet people with a friendly Hi there!")).toBeVisible({ timeout: 30_000 });
  await expect(card.getByText("NEEDS YOU")).toBeVisible({ timeout: 15_000 }); // set when the run ends
  await expect(card.getByRole("group", { name: "Stage: Design (2 of 6)" })).toBeVisible({ timeout: 15_000 });
  const asked = reportFor(reports, BRAINSTORM, `## Task ${KEY}`);
  const resumed = reportFor(reports, ANSWERED);
  expect(asked.session_events).toHaveLength(1);
  expect(asked.session_events![0]).toMatch(/^new:fake-session-\d+$/);
  expect(resumed.session_events).toEqual([asked.session_events![0].replace(/^new:/, "resume:")]);
  expect(resumed.prompts![0]).toContain("Chosen: Friendly");
  await designSection.getByRole("button", { name: "Approve" }).click();
  await expect(drawer.getByText("approved the design v1")).toBeVisible();
  // WF-9: the approved design is filed in the project's Knowledge Base, written by the agent
  type Filed = { kb_documents: { kind: string; document_id: string }[] };
  const filedWf: Filed = await (await page.request.get(`/api/tasks/${KEY}/workflow`)).json();
  const filedDesign = filedWf.kb_documents.find((k) => k.kind === "design")!;
  const filedRevs: { author: { agent: { name: string } | null } }[] = await (
    await page.request.get(`/api/kb/documents/${filedDesign.document_id}/revisions`)
  ).json();
  expect(filedRevs[0].author.agent?.name).toBe(AGENT_NAME);

  // 5. the plan with 2 steps: v1 rejected with a comment, v2 approved; two subtasks
  const planSection = drawer.locator("#document-plan");
  await expect(planSection.getByText("Greeting plan v1")).toBeVisible({ timeout: 30_000 });
  await expect(planSection.getByRole("listitem")).toHaveCount(2);
  // a decision is accepted once the submitting run has ended and the workflow waits for it
  await expect(drawer.getByText("Waiting: Approve the plan")).toBeVisible({ timeout: 15_000 });
  await planSection.getByRole("button", { name: "Reject" }).click();
  await expect(planSection.getByRole("alert")).toHaveText("Add a comment explaining what should change.");
  await planSection.getByLabel("Comment").fill("Split the tests out");
  await planSection.getByRole("button", { name: "Reject" }).click();
  await expect(planSection.getByText("Greeting plan v2")).toBeVisible({ timeout: 30_000 });
  await expect(drawer.getByText("Waiting: Approve the plan")).toBeVisible({ timeout: 15_000 });
  await planSection.getByRole("button", { name: "Approve" }).click();
  await expect(drawer.getByText("approved the plan v2")).toBeVisible();
  await expect(drawer.getByText("Subtasks (0/2)")).toBeVisible();
  await expect(drawer.getByText("Write the greeting").first()).toBeVisible();
  type Sub = { key: string; title: string; type: string; parent_id: string | null };
  const all: (Sub & { id: string })[] = await (await page.request.get("/api/projects/WFL/tasks")).json();
  const parentId = all.find((t) => t.key === KEY)!.id;
  const subs = all.filter((t) => t.parent_id === parentId).map((t) => [t.key, t.type, t.title]);
  expect(subs.sort()).toEqual([
    ["WFL-2", "subtask", "Step 1: Write the greeting"],
    ["WFL-3", "subtask", "Step 2: Wire it up"],
  ]);
  // Build starts with step 1, whose implement run holds for 4 s (see the scenario)
  await expect(card.getByText("1 of 2 steps")).toBeVisible({ timeout: 15_000 });

  // 6. thread links to a document version select that version in the plan view, inside the drawer
  // the first "plan v1" link is "submitted plan v1"; the last "plan v2" one is "approved the plan v2"
  await drawer.getByRole("link", { name: "plan v1" }).first().click();
  await expect(page).toHaveURL(/[?&]task=WFL-1#document-plan-v1$/);
  await expect(drawer).toBeVisible();
  await expect(planSection.getByRole("button", { name: "v1 · rejected (selected)" })).toHaveAttribute("aria-pressed", "true");
  await expect(planSection.getByText("Greeting plan v1")).toBeVisible();
  await drawer.getByRole("link", { name: "plan v2" }).last().click();
  await expect(planSection.getByRole("button", { name: "v2 · approved (selected)" })).toHaveAttribute("aria-pressed", "true");
  await expect(planSection.getByText("Greeting plan v2")).toBeVisible();

  // 7. Build: step 1's run reaches the thread; its review asks for a change, the fix and a fresh re-review
  // approve it
  await expect(drawer.getByText("changed step1.txt (+1 −0)")).toBeVisible({ timeout: 30_000 });
  await expect(drawer.getByText("finished: Step 1 is done")).toBeVisible({ timeout: 30_000 });
  await expect(drawer.getByText("Review of step 1 (round 1): changes requested — 1 important")).toBeVisible({ timeout: 30_000 });
  await drawer.getByRole("button", { name: "Show findings (1)" }).click();
  const findings = drawer.getByRole("region", { name: "Important findings" });
  await expect(findings.getByRole("listitem")).toHaveText("step1.txt:1The greeting has no farewell");
  await expect(drawer.getByText("changed step1.txt (+1 −1)")).toBeVisible({ timeout: 30_000 }); // the fix
  await expect(drawer.getByText("Review of step 1 (round 2): approved")).toBeVisible({ timeout: 30_000 });
  await expect(card.getByText("2 of 2 steps")).toBeVisible({ timeout: 15_000 });

  // 8. the runner goes away during step 2's implement run: that run fails, the same step waits for the runner
  await expect
    .poll(async () => (await runs(page, KEY)).some((r) => r.workflow_role === "implement" && r.step === 2 && r.status === "running"), {
      timeout: 30_000,
    })
    .toBe(true);
  await leftovers.runner!.stop();
  await expect(panel.getByText("Offline", { exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(panel.getByText(`Agent offline — the run starts when ${ADMIN.name}'s runner connects.`)).toBeVisible();
  await expect(panel.getByText("step 2 · implement · queued · workspace")).toBeVisible();
  launch(token);
  await expect(panel.getByText("Online", { exact: true }).or(panel.getByText("Busy", { exact: true }))).toBeVisible({ timeout: 15_000 });

  // 9. In Review by itself, then Done, with the pull request
  await expect(column(page, "In Review").getByRole("button", { name: /WFL-1 Add a greeting/ })).toBeVisible({ timeout: 60_000 });
  const doneCard = column(page, "Done").getByRole("button", { name: /WFL-1 Add a greeting/ });
  await expect(doneCard).toBeVisible({ timeout: 60_000 });
  await expect(doneCard.getByRole("group", { name: "Stage: Done (6 of 6)" })).toBeVisible();
  await expect(panel.getByText("Finished", { exact: true })).toBeVisible();
  await expect(panel.getByRole("link", { name: "PR (not tracked)" })).toHaveAttribute("href", PR_URL); // no git connection
  await expect(panel.getByText(BRANCH)).toBeVisible();
  await expect(drawer.getByText("Moved to In Review by the workflow")).toBeVisible();
  await expect(drawer.getByText("Moved to Done by the workflow")).toBeVisible();
  await expect(drawer.getByText("Subtasks (2/2)")).toBeVisible();
  await expect(drawer.getByText("changed step2.txt (+1 −0)")).toHaveCount(1); // the killed attempt wrote nothing

  // every run, in order: the runner restart re-ran step 2's implement once and nothing before it
  expect((await runs(page, KEY)).map(runLabel)).toEqual([
    "brainstorm completed",
    "brainstorm completed",
    "plan completed",
    "plan completed",
    "implement:1 completed",
    "step_review:1 completed",
    "step_fix:1 completed",
    "step_review:1 completed",
    "implement:2 failed (runner_disconnected)",
    "implement:2 completed",
    "step_review:2 completed",
    "final_review completed",
    "finish completed",
  ]);

  // .megoocolab/plan.md (the approved v2) and design.md were in the worktree during Build
  const step1 = reportFor(reports, IMPLEMENT, STEP(1));
  const [plan, design] = step1.steps.filter((s) => s.type === "report_file");
  expect(plan.exists).toBe(true);
  expect(plan.content).toContain("Greeting plan v2");
  expect(design.exists).toBe(true);
  expect(design.content).toContain("Greet people with a friendly Hi there!");
  // step_fix resumed step 1's implement session; the re-review's second verdict was refused
  const fix = reportFor(reports, FIX);
  expect(fix.session_events).toEqual([step1.session_events![0].replace(/^new:/, "resume:")]);
  const reReview = reportFor(reports, STEP_REVIEW, RE_REVIEW);
  const verdicts = reReview.steps.filter((s) => s.tool === "submit_review");
  expect(verdicts.map((s) => s.ok)).toEqual([true, false]);
  expect(verdicts[1].error ?? verdicts[1].result).toContain("already_submitted");

  // the work is in the worktree on the task branch; the developer's checkout is untouched
  expect(readFileSync(join(worktree, "step1.txt"), "utf8")).toBe("Hi there, and bye!\n");
  expect(readFileSync(join(worktree, "step2.txt"), "utf8")).toBe("uses step1\n");
  expect(git(worktree, "log", "--format=%s", `${repoHead}..HEAD`).split("\n")).toEqual([
    "step 2: wire it up",
    "step 1: address review",
    "step 1: the greeting",
  ]);
  expect(existsSync(join(repo, "step1.txt"))).toBe(false);
  expect(existsSync(join(repo, ".megoocolab"))).toBe(false);
  expect(git(repo, "rev-parse", "HEAD")).toBe(repoHead);
  expect(git(repo, "rev-parse", "--abbrev-ref", "HEAD")).toBe(repoBranch);
  expect(git(repo, "status", "--porcelain")).toBe("");

  // 10. Review Focus 3: a mockup that tries to read cookies, call the API, navigate the top window and post an
  // undeclared choice gets nowhere
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await page.getByLabel("New task in To Do").fill("Mockup sandbox probe");
  await page.getByLabel("New task in To Do").press("Enter");
  await expect(column(page, "To Do").getByText("Mockup sandbox probe")).toBeVisible();
  const probeAssigned = await page.request.patch(`/api/tasks/${PROBE_KEY}`, {
    data: { assignee_agent_id: agentId },
    headers: { "X-Megoo-Client": "web" },
  });
  expect(probeAssigned.ok()).toBeTruthy();
  await drag(page, /WFL-4 Mockup sandbox probe/, "To Do", "In Progress");
  const probeCard = column(page, "In Progress").getByRole("button", { name: /WFL-4 Mockup sandbox probe/ });
  await expect(probeCard.getByText("NEEDS YOU")).toBeVisible({ timeout: 30_000 });
  await probeCard.click();
  const probeDrawer = page.getByRole("dialog", { name: PROBE_KEY });
  await expect(probeDrawer.getByText("Does this probe look right?")).toBeVisible();
  const probeUrl = new RegExp(`/projects/WFL/board\\?task=${PROBE_KEY}$`);
  await expect(page).toHaveURL(probeUrl);
  // the question's own frame (the Mockups panel shows the same version, without choices)
  const probeQuestion = probeDrawer.getByRole("listitem").filter({ has: page.getByText("Does this probe look right?") });
  const frame = probeQuestion.frameLocator('iframe[title="Mockup v1: Sandbox probe"]');
  const probe = frame.locator("#probe");
  await expect(probe).toHaveAttribute("data-done", "1", { timeout: 15_000 });
  await frame.locator("#undeclared").click(); // a person clicking the undeclared choice: still nothing
  await expect(probe).toHaveAttribute("data-fetch-relative", /^blocked /);
  await expect(probe).toHaveAttribute("data-fetch-absolute", /^blocked /);
  await expect(probe).toHaveAttribute("data-cookie", "blocked SecurityError");
  await expect(probe).toHaveAttribute("data-top", "blocked SecurityError");
  await expect(probe).toHaveAttribute("data-csp", "connect-src");
  await expect(probe).toHaveAttribute("data-posted", "zzz");
  // the browser's own reports, logged in the mockup frame
  const fromMockup = consoleLines.filter((l) => l.startsWith(`error @${BASE}/api/mockups/`));
  expect(fromMockup.some((l) => l.includes(`violates the following Content Security Policy directive: "connect-src 'none'"`))).toBe(true);
  expect(fromMockup.some((l) => l.includes("The frame attempting navigation of the top-level window is sandboxed"))).toBe(true);
  expect(page.url()).toMatch(probeUrl); // top.location = "/" did not navigate the app
  await expect(probeDrawer.getByRole("button", { name: /^Yes/ })).toHaveAttribute("aria-pressed", "false");
  await expect(probeDrawer.getByText("Selected in the mockup")).toHaveCount(0);
  await expect(probeDrawer.getByRole("button", { name: "Send answer" })).toBeDisabled();
  const probeActivity: ActivityItem[] = await (await page.request.get(`/api/tasks/${PROBE_KEY}/activity?limit=200`)).json();
  const questions = probeActivity.filter((i) => i.type === "question");
  expect(questions.map((q) => [q.question?.status, q.question?.answer_choice])).toEqual([["open", null]]);
  const probeWf = await (await page.request.get(`/api/tasks/${PROBE_KEY}/workflow`)).json();
  expect([probeWf.status, probeWf.needs]).toEqual(["waiting_human", "question"]);
  // positive control: the frame's choice channel was live all along. A declared choice preselects "Yes" (and,
  // as always, only preselects: still no answer)
  await frame.locator("#declared").click();
  await expect(probeDrawer.getByRole("button", { name: /^Yes/ })).toHaveAttribute("aria-pressed", "true");
  await expect(probeDrawer.getByRole("button", { name: "Send answer" })).toBeEnabled();
  const after: ActivityItem[] = await (await page.request.get(`/api/tasks/${PROBE_KEY}/activity?limit=200`)).json();
  expect(after.filter((i) => i.type === "question").map((q) => q.question?.status)).toEqual(["open"]);
});
