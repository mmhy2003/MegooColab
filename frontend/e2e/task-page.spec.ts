import { expect, test, type APIRequestContext } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";

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

for (const [label, viewport] of [["desktop", { width: 1280, height: 600 }], ["phone", { width: 390, height: 760 }]] as const) {
  test(`composer floats and jump buttons stay clear (${label})`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await setupOrSignIn(page);
    const request = page.request;
    const me = (await (await request.get("/api/auth/me")).json()).user.id as string;
    const key = label === "desktop" ? "TPD" : "TPP";
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

    // tapping into it on a phone makes it grow: the buttons still keep clear
    await page.getByRole("textbox", { name: "Add a comment" }).click();
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
  });
}
