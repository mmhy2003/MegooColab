import { expect, test, type APIRequestContext, type Browser, type BrowserContext } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";

/**
 * End-to-end test of Plan 9: the Ctrl+K box finds a task a member can open, with a typo, within seconds of its
 * creation, and never a task of a project they are not in; "See all results" opens the filtered results page; a
 * rename is found too. Needs a fresh stack (see README "Global search end-to-end test"). Project keys SRA and SRB.
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const BEA = { name: "Bea Searcher", email: "bea.search@acme.io", password: "bea-password-123" };

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

async function invited(browser: Browser, admin: APIRequestContext): Promise<{ ctx: BrowserContext; id: string }> {
  const invite = await post<{ invite_url: string }>(admin, "/api/admin/users/invite", { email: BEA.email, name: BEA.name, role: "member" });
  const ctx = await browser.newContext({ baseURL: BASE });
  await post(ctx.request, "/api/auth/accept-invite", { token: invite.invite_url.split("/invite/")[1], password: BEA.password });
  const me = await get<{ user: { id: string } }>(ctx.request, "/api/auth/me");
  return { ctx, id: me.user.id };
}

const leftovers: { ctxs: BrowserContext[] } = { ctxs: [] };

test.afterEach(async () => {
  for (const c of leftovers.ctxs) await c.close();
  leftovers.ctxs = [];
});

test("search finds what you may open", async ({ browser }) => {
  test.setTimeout(120_000);
  const adminCtx = await browser.newContext();
  leftovers.ctxs.push(adminCtx);
  const admin = await adminCtx.newPage();
  await setupOrSignIn(admin);
  const request = admin.request;
  const adminId = (await get<{ user: { id: string } }>(request, "/api/auth/me")).user.id;

  // SRA has Bea; SRB is the admin's alone
  const bea = await invited(browser, request);
  leftovers.ctxs.push(bea.ctx);
  const shared = await post<{ id: string }>(request, "/api/teams", { name: "Search Team", description: "" });
  expect((await request.put(`/api/teams/${shared.id}/members`, { data: { user_ids: [adminId, bea.id] }, headers: WEB })).ok()).toBeTruthy();
  const own = await post<{ id: string }>(request, "/api/teams", { name: "Search Private", description: "" });
  expect((await request.put(`/api/teams/${own.id}/members`, { data: { user_ids: [adminId] }, headers: WEB })).ok()).toBeTruthy();
  await post(request, "/api/projects", { key: "SRA", name: "Search Alpha", description: "", team_ids: [shared.id] });
  await post(request, "/api/projects", { key: "SRB", name: "Search Beta", description: "", team_ids: [own.id] });
  await post(request, "/api/projects/SRA/tasks", { title: "Retry failed card payments", type: "task" });
  await post(request, "/api/projects/SRB/tasks", { title: "Retry secret rollout", type: "task" });

  // 1. Bea presses Ctrl+K and types with a typo: SRA-1 appears, SRB-1 never does
  const page = await bea.ctx.newPage();
  await page.goto("/projects");
  const box = page.getByRole("combobox", { name: "Search" });
  await expect
    .poll(
      async () => {
        if (!(await box.isVisible())) await page.keyboard.press("Control+K");
        await box.fill("");
        await box.fill("retyr");
        return page.getByRole("option", { name: /SRA-1 Retry failed card payments/ }).waitFor({ state: "visible", timeout: 3_000 }).then(() => true, () => false);
      },
      { timeout: 30_000 },
    )
    .toBe(true);
  await expect(page.getByRole("option", { name: /SRB-1/ })).toHaveCount(0);
  await expect(page.getByRole("option", { name: /secret/i })).toHaveCount(0);

  // 2. Enter opens the task
  await box.press("Enter");
  await expect(page).toHaveURL(/\/projects\/SRA\/tasks\/1$/);
  await expect(page.getByRole("main").getByText("SRA-1").first()).toBeVisible();

  // 3. "See all results" opens the page, and filtering to tasks that are to do keeps SRA-1
  await page.keyboard.press("Control+K");
  await box.fill("retry");
  await page.getByRole("link", { name: /See all \d+ results/ }).click();
  await expect(page).toHaveURL(/\/search\?q=retry$/);
  const results = page.getByRole("main").last();
  await page.getByRole("checkbox", { name: /^Tasks \(\d+\)$/ }).check();
  await page.getByRole("checkbox", { name: /^To do \(\d+\)$/ }).check();
  await expect(page).toHaveURL(/kind=task/);
  await expect(page).toHaveURL(/status=before/);
  await expect(results.getByRole("link", { name: /SRA-1/ })).toBeVisible();
  await expect(results.getByText(/SRB-1/)).toHaveCount(0);

  // 4. the admin renames SRA-1, and Bea's search finds the new title
  const renamed = await request.patch("/api/tasks/SRA-1", { data: { title: "Retry declined card charges" }, headers: WEB });
  expect(renamed.ok()).toBeTruthy();
  await expect
    .poll(
      async () => {
        await page.goto("/search?q=declined");
        return page.getByRole("link", { name: /SRA-1 Retry declined card charges/ }).waitFor({ state: "visible", timeout: 3_000 }).then(() => true, () => false);
      },
      { timeout: 30_000 },
    )
    .toBe(true);
});
