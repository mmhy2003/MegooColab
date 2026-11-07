import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type Browser, type BrowserContext, type Page } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";
import { tool } from "./helpers/mcp";
import { textUnder } from "./helpers/overlap";
import { buildBinaries, mcp, mintLinkedRunnerToken, onPrompt, say, startRunner, type RunnerHandle } from "./helpers/runner";

/**
 * Every page, popup and dialog fits a phone down to 280 pixels wide (a Galaxy Fold's cover screen) and 344 (the newer
 * one): nothing makes the page itself scroll sideways. Wide content (code, a table, a tab bar, the board) may scroll
 * inside its own box, which says so with data-scroll-x; any other box that scrolls sideways is a fault. Creates the
 * "Mobile Team…" team and the MOB and MOC projects, so it needs a fresh stack. The chat needs the Go toolchain and git.
 */

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const WEB = { "X-Megoo-Client": "web" };
const WIDTHS = [280, 344];
const AGENT_NAME = `${ADMIN.name}'s Claude Code`;
const SHOT = join(__dirname, "fixtures", "screenshot.png");
const BRAINSTORM = "# Brainstorm: turn the task into an approved design";

// the content that stretched pages before: a long link, a long identifier, a wide code line, a wide table
const URL_LONG = "https://git.example.com/acme/checkout-service/blob/main/src/components/checkout/PaymentButtonContainer.tsx#L120";
const LONG_MD = [
  `The button is cut off because \`PaymentButtonContainerWithResponsiveWrapperAndFallback\` sets a fixed width. See ${URL_LONG}.`,
  "",
  "```ts",
  `export const PAYMENT_BUTTON_STYLES = { width: 480, minWidth: 480, padding: "12px 24px", boxShadow: "0 1px 2px rgba(0,0,0,.2)" } as const;`,
  "```",
  "",
  "| File | Line | Width | Min width | Breakpoint | Notes |",
  "|---|---|---|---|---|---|",
  "| PaymentButton.tsx | 120 | 480px | 480px | none | fixed width breaks phones |",
].join("\n");

/** What makes the page scroll sideways, and any box scrolling sideways that isn't marked data-scroll-x. */
async function overflow(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    const name = (el: Element) => {
      const label = el.getAttribute("aria-label");
      return `${el.tagName.toLowerCase()}${label ? `[${label}]` : ""}.${String(el.className).slice(0, 60)}`;
    };
    const out: string[] = [];
    if (document.documentElement.scrollWidth > width + 1) {
      // name the widest culprits: elements reaching past the right edge whose parent does not
      for (const el of Array.from(document.body.querySelectorAll<HTMLElement>("*"))) {
        const r = el.getBoundingClientRect();
        const parent = el.parentElement?.getBoundingClientRect();
        if (r.width && r.right > width + 1 && (!parent || parent.right <= width + 1)) {
          out.push(`${name(el)} → ${Math.round(r.right)}px`);
        }
      }
    }
    for (const el of Array.from(document.body.querySelectorAll<HTMLElement>("*"))) {
      const x = getComputedStyle(el).overflowX;
      if ((x === "auto" || x === "scroll") && el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 1 && !el.hasAttribute("data-scroll-x")) {
        out.push(`${name(el)} scrolls sideways by ${el.scrollWidth - el.clientWidth}px`);
      }
    }
    return out.slice(0, 8);
  });
}

async function onScreen(locator: ReturnType<Page["locator"]>, width: number) {
  await expect(locator).toBeVisible();
  const box = (await locator.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(width + 1);
}

async function phone(browser: Browser, width: number, storageState?: Awaited<ReturnType<BrowserContext["storageState"]>>) {
  const ctx = await browser.newContext({ storageState, viewport: { width, height: 653 }, isMobile: true, hasTouch: true });
  return { ctx, page: await ctx.newPage() };
}

async function check(page: Page, paths: string[], problems: Record<string, string[]>, prefix: string) {
  for (const path of paths) {
    await page.goto(path);
    await page.getByRole("main").first().waitFor().catch(() => undefined);
    await page.waitForTimeout(800); // let the data arrive (live pages never go network-idle)
    const found = await overflow(page);
    if (found.length) problems[`${prefix} ${path}`] = found;
  }
}

async function post<T = unknown>(request: APIRequestContext, url: string, data: unknown): Promise<T> {
  const r = await request.post(url, { data, headers: WEB });
  expect(r.ok(), `${url}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return (await r.json().catch(() => null)) as T;
}

test("every page fits a phone, 280 and 344 pixels wide", async ({ browser, page }) => {
  test.setTimeout(300_000);
  await setupOrSignIn(page);
  const request = page.request;
  const me = (await (await request.get("/api/auth/me")).json()).user.id as string;
  // a team name long enough to make KB search's Space option wider than the screen
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Mobile Team with a long name for the space dropdown on phones", description: "" });
  await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB });
  await post(request, "/api/projects", { key: "MOB", name: "Mobile check of a project with a rather long descriptive name", description: "", team_ids: [team.id] });
  await post(request, "/api/projects/MOB/tasks", { title: "A task with a rather long title that must wrap on a narrow phone screen", type: "task" });
  await post(request, "/api/tasks/MOB-1/comments", { body_md: LONG_MD });

  // a design waiting on the dashboard, its title long enough to have to shrink on a phone
  const waiting = await post<{ key: string }>(request, "/api/projects/MOB/tasks", {
    title: `Design ${"a very long title for a narrow screen ".repeat(3)}`.slice(0, 120), type: "task", assignee_user_id: me,
  });
  const token = await post<{ secret: string }>(request, "/api/tokens", { name: "Mobile e2e", scopes: ["mcp"] });
  await tool(request, token.secret, "submit_design", { key: waiting.key, markdown: `# Narrow\n\n${LONG_MD}` });

  // a long agent name (the dashboard's Agents card, My agents) and a long question title (Questions, the question)
  const agent = await post<{ id: string }>(request, "/api/agents", {
    program: "claude_code", max_concurrent_runs: 1, name: `Agent ${"with-a-very-long-unbroken-name".repeat(4)}`,
  });
  await request.put(`/api/agents/${agent.id}/bindings`, {
    // a long folder: My agents keeps it on one line, cut short
    data: { bindings: [{ project_ref: "MOB", local_path: `C:\\${"a-rather-long-folder-name\\".repeat(8)}mob`.slice(0, 200) }] },
    headers: WEB,
  });
  const asked = await post<{ question: { id: string } }>(request, "/api/questions", {
    project_key: "MOB", title: `How ${"does-this-very-long-unbroken-question-title ".repeat(4)}`.slice(0, 200), body: LONG_MD,
  });
  const spaces = (await (await request.get("/api/kb/spaces")).json()) as { id: string; name: string }[];
  const space = spaces.find((s) => /Mobile check/.test(s.name))!;
  const doc = await post<{ id: string }>(request, `/api/kb/spaces/${space.id}/documents`, { title: "Checkout notes", body_md: LONG_MD, folder_id: null });

  const pages = [
    "/", "/chats", "/projects", "/projects/MOB", "/projects/MOB/board", "/projects/MOB/chats", "/projects/MOB/backlog",
    "/projects/MOB/tasks/1", "/projects/MOB/reports", "/projects/MOB/settings", "/teams", `/teams/${team.id}`, "/kb",
    `/kb/${space.id}`, `/kb/doc/${doc.id}`, "/kb/search", "/memory", "/hub", "/hub/new-mcp", "/hub/new-skill", "/questions",
    "/search?q=checkout", `/questions/${asked.question.id}`, "/notifications", "/settings", "/settings/profile",
    "/settings/tokens", "/settings/agents", `/settings/agents?agent=${agent.id}`, "/settings/agents?tab=tools",
    "/settings/agents?tab=runner&machine=new", "/settings/notifications", "/change-password", "/admin", "/admin/users",
    "/admin/agents", "/admin/settings", "/admin/methodology", "/admin/ai", "/admin/git", "/admin/audit",
  ];
  const state = await page.context().storageState();
  const problems: Record<string, string[]> = {};
  for (const width of WIDTHS) {
    const anon = await phone(browser, width);
    await check(anon.page, ["/login", "/forgot"], problems, `${width}`);
    await anon.ctx.close();

    const { ctx, page: p } = await phone(browser, width, state);
    await check(p, pages, problems, `${width}`);

    // the user menu, the notification panel, search, the main menu and the assignee list stay on the screen
    await p.goto("/projects");
    await p.getByRole("button", { name: /Root Admin/ }).click();
    await onScreen(p.getByRole("menu"), width);
    await p.keyboard.press("Escape");
    await p.getByRole("button", { name: "Notifications" }).click();
    await onScreen(p.getByRole("dialog", { name: "Notifications" }), width);
    await p.keyboard.press("Escape");
    await p.getByRole("button", { name: "Search" }).click();
    await onScreen(p.getByRole("dialog", { name: "Search" }), width);
    await p.keyboard.press("Escape");
    await p.getByRole("button", { name: "Open menu" }).click();
    await onScreen(p.getByRole("navigation", { name: "Main" }), width);
    await p.keyboard.press("Escape");
    await p.goto("/projects/MOB/tasks/1");
    // on a phone the details are folded to a line; Show all opens them
    await p.getByRole("button", { name: "Show all details" }).click();
    await p.getByRole("combobox", { name: "Assignee" }).click();
    await onScreen(p.getByRole("listbox"), width);
    await p.keyboard.press("Escape");
    await p.getByRole("button", { name: "Delete task" }).click();
    await onScreen(p.getByRole("alertdialog").or(p.getByRole("dialog")).last(), width);
    await p.keyboard.press("Escape");
    await p.goto("/settings/agents");
    await p.getByRole("button", { name: "Add agent" }).click();
    await onScreen(p.getByRole("dialog", { name: "Add agent" }), width);
    await p.keyboard.press("Escape");
    await p.goto("/settings/tokens");
    await p.getByRole("button", { name: /New token|Create token/ }).first().click();
    await onScreen(p.getByRole("dialog").last(), width);
    await p.keyboard.press("Escape");
    // a repository entered by hand: its form fits too
    await p.goto("/projects/MOB/settings");
    await p.getByRole("tab", { name: "Repositories" }).click();
    await p.getByRole("button", { name: "Enter it by hand" }).click();
    await expect(p.getByLabel("Repository URL")).toBeVisible();
    expect(await overflow(p), `repository form at ${width}`).toEqual([]);

    // long titles wrap rather than being cut or squeezed out
    await p.goto("/projects/MOB/backlog");
    const row = p.getByRole("button", { name: /A task with a rather long title/ });
    await expect(row).toBeVisible();
    expect((await row.boundingBox())!.width).toBeGreaterThan(150);
    await p.goto("/projects/MOB/tasks/1");
    const title = p.getByRole("textbox", { name: "Title" });
    await expect(title).toHaveValue(/must wrap on a narrow phone screen/);
    expect(await title.evaluate((el) => el.scrollHeight <= el.clientHeight + 1 && el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    await ctx.close();
  }
  // later specs expect the admin to have one agent: the long-named one has done its job
  const removed = await request.delete(`/api/agents/${agent.id}`, { headers: WEB });
  expect(removed.ok(), await removed.text()).toBeTruthy();
  expect(problems).toEqual({});
});

function git(cwd: string, ...args: string[]) {
  execFileSync("git", ["-c", "user.name=E2E", "-c", "user.email=e2e@acme.io", ...args], { cwd, stdio: "pipe" });
}

const leftovers: { runner?: RunnerHandle; work?: string } = {};

test.afterEach(async () => {
  const { runner, work } = leftovers;
  delete leftovers.runner;
  delete leftovers.work;
  await runner?.stop();
  if (work) rmSync(work, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
});

test("chats on a phone", async ({ browser, page }) => {
  test.setTimeout(300_000);
  const work = mkdtempSync(join(tmpdir(), "megoo-e2e-mobile-"));
  leftovers.work = work;
  await setupOrSignIn(page);
  const request = page.request;
  const me = (await (await request.get("/api/auth/me")).json()).user.id as string;
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Mobile Chat Team", description: "" });
  await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB });
  await post(request, "/api/projects", { key: "MOC", name: "Mobile chats", description: "", team_ids: [team.id] });
  await request.patch("/api/projects/MOC", { data: { sprints_enabled: false }, headers: WEB });
  const bins = buildBinaries(join(work, "bin"));
  const repo = join(work, "repo");
  mkdirSync(repo);
  git(repo, "init", "-q");
  writeFileSync(join(repo, "README.md"), "# checkout\n");
  git(repo, "add", ".");
  git(repo, "commit", "-q", "-m", "init");
  type Agent = { id: string; name: string; status: string };
  const mine = (await (await request.get("/api/agents/mine")).json()) as Agent[];
  const agent = mine.find((a) => a.name === AGENT_NAME) ?? (await post<Agent>(request, "/api/agents", { program: "claude_code" }));
  const bound = await request.put(`/api/agents/${agent.id}/bindings`, { data: { bindings: [{ project_ref: "MOC", local_path: repo }] }, headers: WEB });
  expect(bound.ok(), await bound.text()).toBeTruthy();
  const token = await mintLinkedRunnerToken(request, agent.id, "Mobile");
  leftovers.runner = startRunner({
    url: BASE, token, home: join(work, "home"), adapterOverride: bins.fakeAgent, runnerBin: bins.runner, env: { FAKEAGENT_IMAGES: "1" },
    scenario: [onPrompt(BRAINSTORM, say(LONG_MD), mcp("submit_design", { key: "MOC-1", markdown: `# Checkout fits every phone\n\n${LONG_MD}` }))],
  });
  await expect
    .poll(async () => ((await (await request.get("/api/agents/mine")).json()) as Agent[]).find((a) => a.id === agent.id)?.status, { timeout: 20_000 })
    .toBe("online");

  // a chat whose first message carries a long link and an image, started at desktop size
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto("/projects/MOC/chats");
  await page.getByRole("button", { name: "New chat" }).click();
  const dialog = page.getByRole("dialog", { name: "New chat" });
  await dialog.getByLabel("Message").fill(`The checkout button is cut off on my phone, see ${URL_LONG}`);
  await dialog.locator('input[type="file"]').setInputFiles(SHOT);
  await expect(dialog.getByRole("button", { name: "Remove screenshot.png" })).toBeVisible();
  await dialog.getByRole("button", { name: "Start chat" }).click();
  await expect(page).toHaveURL(/\/chats\/[0-9a-f-]{36}$/);
  const chat = new URL(page.url()).pathname;
  await expect(page.getByRole("main").getByText("Checkout fits every phone").first()).toBeVisible({ timeout: 40_000 });

  const state = await page.context().storageState();
  for (const width of WIDTHS) {
    const { ctx, page: p } = await phone(browser, width, state);
    const problems: Record<string, string[]> = {};
    await check(p, ["/chats", "/projects/MOC/chats", chat], problems, `${width}`);
    expect(problems).toEqual({});
    // the conversation gets most of the screen
    const thread = (await p.locator("[data-thread]").boundingBox())!;
    expect(thread.height).toBeGreaterThanOrEqual(653 * 0.45);
    // it opens at the latest, following: the "Following live" note covers no text
    const note = p.getByRole("status").filter({ hasText: "Following live" });
    await expect(note).toBeVisible();
    expect(await textUnder(note, p.locator("[data-thread]"))).toEqual([]);
    const messages = (await p.locator("[data-thread] > div").first().boundingBox())!;
    expect((await note.boundingBox())!.y).toBeGreaterThanOrEqual(messages.y + messages.height);
    // its popups open on the screen
    await p.getByRole("button", { name: "Open screenshot.png" }).first().click();
    await onScreen(p.getByRole("dialog", { name: "screenshot.png" }), width);
    await p.keyboard.press("Escape");
    await p.getByRole("button", { name: "Chat actions" }).click();
    await onScreen(p.getByRole("menu"), width);
    await p.keyboard.press("Escape");
    await p.goto("/projects/MOC/chats");
    await p.getByRole("button", { name: "New chat" }).first().click();
    await onScreen(p.getByRole("dialog", { name: "New chat" }), width);
    await p.keyboard.press("Escape");
    await ctx.close();
  }
});

test("the board on a phone", async ({ browser, page }) => {
  await setupOrSignIn(page);
  const request = page.request;
  const me = (await (await request.get("/api/auth/me")).json()).user.id as string;
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Mobile Board Team", description: "" });
  await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB });
  await post(request, "/api/projects", { key: "MBD", name: "Mobile board", description: "", team_ids: [team.id] });
  await request.patch("/api/projects/MBD", { data: { sprints_enabled: false }, headers: WEB });
  for (const title of ["First card with a long title that wraps on a phone", "Second card", "Third card"]) {
    await post(request, "/api/projects/MBD/tasks", { title, type: "task" });
  }
  const { ctx, page: p } = await phone(browser, 280, await page.context().storageState());
  await p.goto("/projects/MBD/board");
  const card = p.getByText("First card with a long title");
  await expect(card).toBeVisible();
  expect(await overflow(p)).toEqual([]);
  // the first column and its first card are whole on the screen
  const box = (await card.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(281);
  await ctx.close();
});


test("my agents on a phone: list, details, Back", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await setupOrSignIn(page);
  const name = "Phone agent";
  const agent = await (await page.request.post("/api/agents", { data: { program: "claude_code", name }, headers: WEB })).json();
  try {
    await page.goto("/settings/agents");
    const list = page.getByRole("navigation", { name: "Agents", exact: true });
    const details = page.getByRole("region", { name });
    const row = list.getByRole("button", { name: new RegExp(`^${name}`) });
    await expect(row).toBeVisible();
    await expect(details).toBeHidden();

    // tapping the agent opens its details full screen; the browser's Back returns to the list
    await row.click();
    await expect(details).toBeVisible();
    await expect(list).toBeHidden();
    expect(await overflow(page)).toEqual([]);
    await page.goBack();
    await expect(row).toBeVisible();
    await expect(details).toBeHidden();

    // and so does the page's own Back
    await row.click();
    await expect(details).toBeVisible();
    await page.getByRole("button", { name: "‹ Agents" }).click();
    await expect(row).toBeVisible();
    await expect(details).toBeHidden();
    expect(await overflow(page)).toEqual([]);
  } finally {
    // later specs expect the admin's agents as they left them
    await page.request.delete(`/api/agents/${agent.id}`, { headers: WEB });
  }
});
