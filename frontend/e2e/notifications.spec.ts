import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type Browser, type BrowserContext, type Page } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { buildBinaries, mcp, onPrompt, startRunner, type RunnerHandle } from "./helpers/runner";
import { pickAssignee } from "./helpers/assignee";

/**
 * End-to-end test of Plan 7's notifications: an assignment and a mention reach the person through the bell (and an
 * outsider mentioned by hand gets nothing), the agent's owner is told when the workflow waits for a design
 * approval, and turning a kind off in-app silences it. Needs the Go toolchain and git on the PATH, and a fresh
 * stack (see README "Git and notifications end-to-end tests"). Project key NOT.
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;
const BEA = { name: "Bea Notified", email: "bea@acme.io", password: "bea-password-123" };
const OUT = { name: "Nils Outside", email: "nils@acme.io", password: "nils-password-123" };
const BRAINSTORM = "# Brainstorm: turn the task into an approved design";

type Notification = { kind: string; title: string; link: string; read_at: string | null };
type Me = { user: { id: string } };

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
    .toString()
    .trim();
}

/** Invites someone as the admin and signs them in, in a context of their own. */
async function invited(browser: Browser, admin: APIRequestContext, who: typeof BEA): Promise<{ ctx: BrowserContext; id: string }> {
  const invite = await post<{ invite_url: string; user: { id: string } }>(admin, "/api/admin/users/invite", {
    email: who.email,
    name: who.name,
    role: "member",
  });
  const ctx = await browser.newContext({ baseURL: BASE });
  await post(ctx.request, "/api/auth/accept-invite", { token: invite.invite_url.split("/invite/")[1], password: who.password });
  const me = await get<Me>(ctx.request, "/api/auth/me");
  return { ctx, id: me.user.id };
}

function bell(page: Page) {
  return page.getByRole("button", { name: "Notifications" });
}

const leftovers: { runner?: RunnerHandle; ctxs: BrowserContext[]; work?: string } = { ctxs: [] };

test.afterEach(async () => {
  const { runner, ctxs, work } = leftovers;
  delete leftovers.runner;
  delete leftovers.work;
  leftovers.ctxs = [];
  await runner?.stop();
  if (process.env.E2E_RUNNER_LOG) console.log(runner?.output());
  for (const c of ctxs) await c.close();
  if (work) rmSync(work, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
});

test("notifications reach the right people", async ({ browser }) => {
  test.setTimeout(240_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-notifications-"));
  leftovers.work = work;

  const adminCtx = await browser.newContext();
  leftovers.ctxs.push(adminCtx);
  const page = await adminCtx.newPage();
  await setupOrSignIn(page);
  const request = page.request;
  const adminId = (await get<Me>(request, "/api/auth/me")).user.id;

  // project NOT with the admin and Bea; Otto is in no team of it
  const bea = await invited(browser, request, BEA);
  const otto = await invited(browser, request, OUT);
  leftovers.ctxs.push(bea.ctx, otto.ctx);
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Notify Team", description: "" });
  const members = await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [adminId, bea.id] }, headers: WEB });
  expect(members.ok(), await members.text()).toBeTruthy();
  await post(request, "/api/projects", { key: "NOT", name: "Notify Demo", description: "", team_ids: [team.id] });
  expect((await request.patch("/api/projects/NOT", { data: { sprints_enabled: false }, headers: WEB })).ok()).toBeTruthy();
  await post(request, "/api/projects/NOT/tasks", { title: "Review the copy", type: "task" });

  // 1. the admin assigns NOT-1 to Bea: her bell shows 1, and the notification opens the task
  await page.goto("/projects/NOT/board?task=NOT-1");
  const drawer = page.getByRole("dialog", { name: "NOT-1" });
  await pickAssignee(drawer, BEA.name);
  await expect(drawer.getByText(`assigned this to ${BEA.name}`)).toBeVisible();
  const beaPage = await bea.ctx.newPage();
  await beaPage.goto("/projects");
  await expect(bell(beaPage)).toHaveText("1", { timeout: 15_000 });
  await bell(beaPage).click();
  await beaPage.getByRole("link", { name: `${ADMIN.name} assigned you NOT-1` }).click();
  await expect(beaPage).toHaveURL(/\/projects\/NOT\/board\?task=NOT-1$/);
  await expect(beaPage.getByRole("dialog", { name: "NOT-1" })).toBeVisible();
  await expect(bell(beaPage)).toHaveText("", { timeout: 15_000 }); // read: no badge
  await beaPage.keyboard.press("Escape"); // the drawer is modal: close it to reach the bell again
  await expect(beaPage.getByRole("dialog", { name: "NOT-1" })).toBeHidden();

  // 2. the admin mentions Bea with the picker; Otto, mentioned by hand, cannot read NOT-1 and hears nothing
  const box = drawer.getByLabel("Add a comment");
  await box.fill("Please check the wording @Be");
  // the list opens over the page, outside the drawer's own box
  await page.getByRole("listbox", { name: "Mention someone" }).getByRole("option", { name: BEA.name }).click();
  await expect(box).toHaveValue(`Please check the wording @[${BEA.name}](user:${bea.id}) `);
  await drawer.getByRole("button", { name: "Comment" }).click();
  await expect(drawer.getByText(`@${BEA.name}`)).toBeVisible();
  await post(request, "/api/tasks/NOT-1/comments", { body_md: `FYI @[${OUT.name}](user:${otto.id})` });
  await expect(bell(beaPage)).toHaveText("1", { timeout: 15_000 });
  await bell(beaPage).click();
  await expect(beaPage.getByRole("link", { name: `${ADMIN.name} mentioned you on NOT-1` })).toBeVisible();
  await beaPage.keyboard.press("Escape");
  expect(await get<Notification[]>(otto.ctx.request, "/api/notifications")).toEqual([]);

  // 3. the admin's agent finishes brainstorming NOT-2: the workflow waits on the design, and its owner is told
  const bins = buildBinaries(join(work, "bin"));
  const repo = join(work, "repo");
  mkdirSync(repo);
  git(repo, "init", "-q");
  writeFileSync(join(repo, "README.md"), "# copy\n");
  git(repo, "add", ".");
  git(repo, "commit", "-q", "-m", "init");
  type Agent = { id: string; name: string; status: string };
  const mine = await get<Agent[]>(request, "/api/agents/mine");
  const agent = mine.find((a) => a.name === AGENT_NAME) ?? (await post<Agent>(request, "/api/agents", { program: "claude_code" }));
  const bound = await request.put(`/api/agents/${agent.id}/bindings`, {
    data: { bindings: [{ project_ref: "NOT", local_path: repo }] },
    headers: WEB,
  });
  expect(bound.ok(), await bound.text()).toBeTruthy();
  const token = (await post<{ secret: string }>(request, "/api/tokens", { name: "Notify runner", scopes: ["runner"] })).secret;
  leftovers.runner = startRunner({
    url: BASE,
    token,
    home: join(work, "home"),
    adapterOverride: bins.fakeAgent,
    scenario: [onPrompt(BRAINSTORM, mcp("submit_design", { key: "NOT-2", markdown: "# Copy design\n\nShorter words." }))],
    runnerBin: bins.runner,
  });
  await expect
    .poll(async () => (await get<Agent[]>(request, "/api/agents/mine")).find((a) => a.id === agent.id)?.status, { timeout: 20_000 })
    .toBe("online");
  await post(request, "/api/projects/NOT/tasks", { title: "Rewrite the copy", type: "task", assignee_agent_id: agent.id });
  await post(request, "/api/tasks/NOT-2/workflow/start", {});
  await page.keyboard.press("Escape");
  await page.goto("/projects/NOT/board");
  await expect(bell(page)).toHaveText(/^\d+$/, { timeout: 60_000 });
  await bell(page).click();
  const needsYou = page.getByRole("link", { name: "NOT-2: the design awaits your approval" });
  await expect(needsYou).toBeVisible();
  await expect(needsYou).toHaveAttribute("href", "/projects/NOT/board?task=NOT-2");
  const adminNotes = await get<Notification[]>(request, "/api/notifications");
  // once, though the stack's other specs may have left the admin notifications of their own
  const forNot = adminNotes.filter((n) => n.kind === "needs_you" && n.link.startsWith("/projects/NOT/"));
  expect(forNot.map((n) => n.title)).toEqual(["NOT-2: the design awaits your approval"]);

  // 4. Bea turns assignments off in the app: the next one adds nothing to her bell
  await beaPage.goto("/settings/notifications");
  const inApp = beaPage.getByRole("checkbox", { name: "In app: Assigned to me" });
  await expect(inApp).toBeChecked();
  await inApp.uncheck();
  await expect.poll(async () => (await get<{ kind: string; in_app: boolean }[]>(bea.ctx.request, "/api/me/notification-preferences"))
    .find((p) => p.kind === "assigned")?.in_app).toBe(false);
  const before = (await get<{ count: number }>(bea.ctx.request, "/api/notifications/unread-count")).count;
  await post(request, "/api/projects/NOT/tasks", { title: "Proofread", type: "task", assignee_user_id: bea.id });
  expect((await get<{ count: number }>(bea.ctx.request, "/api/notifications/unread-count")).count).toBe(before);
  const beaNotes = await get<Notification[]>(bea.ctx.request, "/api/notifications");
  expect(beaNotes.map((n) => n.title)).not.toContain(`${ADMIN.name} assigned you NOT-3`);
});
