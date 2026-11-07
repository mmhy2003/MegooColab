import { expect, test, type APIRequestContext } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";
import { textUnder } from "./helpers/overlap";

/**
 * A task's own page scrolls inside its card, as the drawer does, so the corner buttons (↑ top, ↓ latest and follow)
 * stay in view and work. Creates the "Task Page Team" team and the TPG project, so it needs a fresh stack.
 */

const WEB = { "X-Megoo-Client": "web" };

async function post<T = unknown>(request: APIRequestContext, url: string, data: unknown): Promise<T> {
  const r = await request.post(url, { data, headers: WEB });
  expect(r.ok(), `${url}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return (await r.json()) as T;
}

test("a task's own page keeps the corner buttons in view, and they scroll the task", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 600 });
  await setupOrSignIn(page);
  const request = page.request;
  const me = (await (await request.get("/api/auth/me")).json()).user.id as string;
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Task Page Team", description: "" });
  expect((await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB })).ok()).toBeTruthy();
  await post(request, "/api/projects", { key: "TPG", name: "Task page", description: "", team_ids: [team.id] });
  const long = Array.from({ length: 60 }, (_, i) => `Paragraph ${i + 1} of a long description.`).join("\n\n");
  const task = await post<{ key: string; number: number }>(request, "/api/projects/TPG/tasks", {
    title: "A long task", type: "task", description_md: long,
  });

  await page.goto(`/projects/TPG/tasks/${task.number}`);
  await expect(page.getByText("Paragraph 60 of a long description.")).toBeAttached();
  const latest = page.getByRole("button", { name: /^Go to the latest/ });
  await expect(latest).toBeInViewport();
  await latest.click();
  await expect(page.getByText("Following live")).toBeInViewport();
  const top = page.getByRole("button", { name: "Back to top" });
  await expect(top).toBeInViewport();
  // the task scrolls inside its card: the page itself doesn't, so the header and the buttons stay put
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  await top.click();
  await expect(page.getByRole("textbox", { name: "Title" })).toBeInViewport();
});

/** Where the floating comment box, its scroller and the corner buttons are, in viewport pixels. */
async function geometry(page: import("@playwright/test").Page) {
  return page.evaluate(() => {
    const composer = document.querySelector<HTMLElement>("[data-composer]")!;
    let scroller = composer.parentElement!;
    while (getComputedStyle(scroller).overflowY !== "auto") scroller = scroller.parentElement!;
    const box = composer.getBoundingClientRect();
    const view = scroller.getBoundingClientRect();
    const buttons = [...document.querySelectorAll<HTMLElement>("[data-jump-buttons] button")].map((b) => b.getBoundingClientRect());
    const overlap = buttons.some((b) => b.left < box.right && b.right > box.left && b.top < box.bottom && b.bottom > box.top);
    return { composerTop: box.top, composerBottom: box.bottom, viewBottom: view.bottom, overlap, buttons: buttons.length };
  });
}

const SIZES = [
  ["desktop", { width: 1280, height: 600 }, "TPD"],
  ["phone", { width: 390, height: 760 }, "TPP"],
  ["narrow phone", { width: 280, height: 640 }, "TPN"],
] as const;

for (const [label, viewport, key] of SIZES) {
  test(`composer floats and jump buttons stay clear (${label})`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await setupOrSignIn(page);
    const request = page.request;
    const me = (await (await request.get("/api/auth/me")).json()).user.id as string;
    const team = await post<{ id: string }>(request, "/api/teams", { name: `Composer ${label}`, description: "" });
    expect((await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB })).ok()).toBeTruthy();
    await post(request, "/api/projects", { key, name: `Composer ${label}`, description: "", team_ids: [team.id] });
    const long = Array.from({ length: 60 }, (_, i) => `Paragraph ${i + 1} of a long description.`).join("\n\n");
    const task = await post<{ key: string; number: number }>(request, `/api/projects/${key}/tasks`, {
      title: "A long task", type: "task", description_md: long,
    });
    for (let i = 0; i < 3; i++) await post(request, `/api/tasks/${task.key}/comments`, { body_md: `Comment ${i}` });
    await page.goto(`/projects/${key}/tasks/${task.number}`);
    await expect(page.getByText("Paragraph 60 of a long description.")).toBeAttached();

    // at the top of a long task the box floats at the bottom edge, with the buttons above it
    const top = await geometry(page);
    expect(Math.abs(top.composerBottom - top.viewBottom)).toBeLessThanOrEqual(2);
    expect(top.overlap).toBe(false);

    // tapping into it makes it grow (on a phone it waits as a one-line bar, which opens the form): the buttons still
    // keep clear
    if (label !== "desktop") await page.getByRole("button", { name: "Add a comment…" }).click();
    else await page.getByRole("textbox", { name: "Add a comment" }).click();
    await page.waitForTimeout(300);
    expect((await geometry(page)).overlap).toBe(false);
    expect(await page.evaluate(() => window.scrollY)).toBe(0);

    // at the end it settles under the last comment
    await page.getByRole("button", { name: /^Go to the latest/ }).click();
    await page.waitForTimeout(800);
    const last = await page.getByText("Comment 2").boundingBox();
    const end = await geometry(page);
    expect(last!.y + last!.height).toBeLessThanOrEqual(end.composerTop + 1);
    expect(end.overlap).toBe(false);
    // following, the "Following live" note sits in the room left under the newest comment, covering no text
    const note = page.getByRole("status").filter({ hasText: "Following live" });
    await expect(note).toBeVisible();
    expect(await textUnder(note, page.locator("main"))).toEqual([]);
    const activity = (await page.getByRole("region", { name: "Activity" }).boundingBox())!;
    expect((await note.boundingBox())!.y).toBeGreaterThanOrEqual(activity.y + activity.height);
  });
}

test("a task's own page expands over the whole window, centred, and Esc puts it back", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 700 });
  await setupOrSignIn(page);
  const request = page.request;
  const me = (await (await request.get("/api/auth/me")).json()).user.id as string;
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Task Expand Team", description: "" });
  expect((await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB })).ok()).toBeTruthy();
  await post(request, "/api/projects", { key: "TPX", name: "Task expand", description: "", team_ids: [team.id] });
  const long = Array.from({ length: 60 }, (_, i) => `Paragraph ${i + 1} of a long description.`).join("\n\n");
  const task = await post<{ number: number }>(request, "/api/projects/TPX/tasks", { title: "A wide task", type: "task", description_md: long });

  await page.goto(`/projects/TPX/tasks/${task.number}`);
  const card = page.locator("[data-task-page]");
  const inTask = (x: number, y: number) =>
    page.evaluate(([px, py]) => !!document.elementFromPoint(px, py)?.closest("[data-task-page]"), [x, y]);
  await page.getByRole("button", { name: "Expand task" }).click();
  await expect.poll(async () => (await card.boundingBox())!.x).toBe(0);
  expect(await card.boundingBox()).toEqual({ x: 0, y: 0, width: 1600, height: 700 });
  expect(await inTask(40, 350)).toBe(true); // where the menu was
  expect(await inTask(1200, 20)).toBe(true); // where the top bar was
  // the task and its details keep to a centred 80rem (1280px): 160px either side, then the usual 1rem
  const title = (await page.getByRole("textbox", { name: "Title" }).boundingBox())!;
  expect(title.x).toBeGreaterThanOrEqual(176);
  expect(title.x).toBeLessThan(200);
  const details = (await page.getByRole("combobox", { name: "Priority" }).boundingBox())!;
  expect(details.x + details.width).toBeLessThanOrEqual(1600 - 176 + 1);
  expect(details.x + details.width).toBeGreaterThan(1600 - 200);
  await expect(page.getByRole("button", { name: /^Go to the latest/ })).toBeInViewport();

  // Esc while writing the title keeps it expanded; remembered across a reload; Esc elsewhere puts it back
  await page.getByRole("textbox", { name: "Title" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Collapse task" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Collapse task" })).toBeVisible();
  expect(await inTask(40, 350)).toBe(true);
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Expand task" })).toBeVisible();
  expect((await card.boundingBox())!.x).toBeGreaterThan(0);
  expect(await inTask(40, 350)).toBe(false);
});
