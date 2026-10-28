import { expect, test, type Page } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";

/**
 * Popups and clicks outside them: search, the notification panel and the user menu close; a dialog you type in
 * and the task drawer stay open (Escape or ✕ closes them). The page behind every one of them is blurred. Creates
 * the "Popup Team" team and the POP project, so it needs a fresh stack. E2E_SCREENSHOT_DIR=<dir> saves screenshots.
 */

const WEB = { "X-Megoo-Client": "web" };
const shots = process.env.E2E_SCREENSHOT_DIR;

async function shot(page: Page, name: string) {
  if (shots) await page.screenshot({ path: `${shots}/popup-${name}.png` });
}

const blurred = (filter: string) => expect(filter).toMatch(/blur\(/);

async function backdropFilter(page: Page) {
  return page.locator("[data-backdrop]").first().evaluate((el) => getComputedStyle(el).backdropFilter);
}

test("clicks outside popups", async ({ page }) => {
  await setupOrSignIn(page);
  const me = (await (await page.request.get("/api/auth/me")).json()).user.id as string;
  const team = await (await page.request.post("/api/teams", { data: { name: "Popup Team", description: "" }, headers: WEB })).json();
  await page.request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB });
  expect((await page.request.post("/api/projects", { data: { key: "POP", name: "Popups", description: "", team_ids: [team.id] }, headers: WEB })).ok()).toBeTruthy();
  expect((await page.request.post("/api/projects/POP/tasks", { data: { title: "Check the popups", type: "task" }, headers: WEB })).ok()).toBeTruthy();
  await page.goto("/projects");

  // 1. the user menu closes on a click outside it
  await page.getByRole("button", { name: /Root Admin/ }).click();
  await expect(page.getByRole("menu")).toBeVisible();
  blurred(await backdropFilter(page));
  await shot(page, "user-menu");
  await page.mouse.click(400, 500);
  await expect(page.getByRole("menu")).toHaveCount(0);

  // 2. the notification panel closes on a click outside it, and on Escape
  const bell = page.getByRole("button", { name: "Notifications" });
  const panel = page.getByRole("dialog", { name: "Notifications" });
  await bell.click();
  await expect(panel).toBeVisible();
  await shot(page, "notifications");
  await page.mouse.click(400, 500);
  await expect(panel).toHaveCount(0);
  await bell.click();
  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);

  // 3. the header button shows its shortcut; search opens with the cursor in the field, and closes on a click
  // outside it
  await expect(page.getByRole("button", { name: "Search (Ctrl+K)" }).getByText("Ctrl K")).toBeVisible();
  await page.keyboard.press("Control+K");
  const search = page.getByRole("dialog", { name: "Search" });
  await expect(search).toBeVisible();
  await expect(search.getByRole("combobox", { name: "Search" })).toBeFocused();
  await page.keyboard.type("pop");
  await expect(search.getByRole("combobox", { name: "Search" })).toHaveValue("pop");
  blurred(await search.evaluate((el) => getComputedStyle(el, "::backdrop").backdropFilter));
  await shot(page, "search");
  await page.mouse.click(10, 10);
  await expect(search).toHaveCount(0);

  // 4. a dialog you type in stays open on a click outside it, with what was typed
  await page.goto("/teams");
  await page.getByRole("button", { name: "New team" }).click();
  const dialog = page.getByRole("dialog", { name: "New team" });
  await dialog.getByLabel("Name").fill("Half typed");
  await shot(page, "new-team");
  await page.mouse.click(10, 10);
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Name")).toHaveValue("Half typed");
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);

  // 5. the task drawer stays open on a click outside it
  await page.goto("/projects/POP/backlog?task=POP-1"); // a new project has no sprint, so its board is empty
  const drawer = page.getByRole("dialog", { name: "POP-1" });
  await expect(drawer.getByRole("link", { name: "Open full page" })).toBeVisible();
  blurred(await backdropFilter(page));
  await shot(page, "task-drawer");
  await page.mouse.click(10, 300);
  await expect(drawer).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
});
