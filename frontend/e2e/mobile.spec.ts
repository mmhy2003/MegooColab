import { expect, test, type Page } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";

/**
 * Every page fits a 280-pixel-wide screen (a Galaxy Fold's cover screen): nothing makes the page itself scroll
 * sideways. Wide content (a board's columns, a table) may scroll inside its own box. Creates the "Mobile Team" team and
 * the MOB project, so it needs a fresh stack.
 */

const WEB = { "X-Megoo-Client": "web" };

async function overflow(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    if (document.documentElement.scrollWidth <= width) return [];
    // name the widest culprits: elements reaching past the right edge whose parent does not
    const out: string[] = [];
    // content inside a box that scrolls or clips sideways is fine: that box is what the page sees
    const contained = (el: HTMLElement) => {
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        if (getComputedStyle(p).overflowX !== "visible") return true;
      }
      return false;
    };
    for (const el of Array.from(document.body.querySelectorAll<HTMLElement>("*"))) {
      if (contained(el)) continue;
      const r = el.getBoundingClientRect();
      const parent = el.parentElement?.getBoundingClientRect();
      if (r.right > width + 1 && (!parent || parent.right <= width + 1)) {
        out.push(`${el.tagName.toLowerCase()}.${String(el.className).slice(0, 60)} → ${Math.round(r.right)}px`);
      }
    }
    return out.slice(0, 5);
  });
}

test("every page fits a 280-pixel screen", async ({ page }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 280, height: 653 });
  await page.goto("/login");
  expect(await overflow(page), "/login").toEqual([]);

  await setupOrSignIn(page);
  const me = (await (await page.request.get("/api/auth/me")).json()).user.id as string;
  const team = await (await page.request.post("/api/teams", { data: { name: "Mobile Team", description: "" }, headers: WEB })).json();
  await page.request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB });
  await page.request.post("/api/projects", { data: { key: "MOB", name: "Mobile check", description: "", team_ids: [team.id] }, headers: WEB });
  await page.request.post("/api/projects/MOB/tasks", {
    data: { title: "A task with a rather long title that must wrap on a narrow phone screen", type: "task" },
    headers: WEB,
  });

  const pages = [
    "/projects", "/projects/MOB/board", "/projects/MOB/backlog", "/projects/MOB/tasks/1", "/projects/MOB/reports",
    "/projects/MOB/settings", "/teams", `/teams/${team.id}`, "/kb", "/memory", "/questions", "/search?q=task",
    "/notifications", "/settings/profile", "/settings/tokens", "/settings/agents", "/settings/notifications",
    "/admin/users", "/admin/agents", "/admin/settings", "/admin/methodology", "/admin/ai", "/admin/git", "/admin/audit",
  ];
  const problems: Record<string, string[]> = {};
  for (const path of pages) {
    await page.goto(path);
    await page.getByRole("main").first().waitFor();
    await page.waitForTimeout(800); // let the data arrive (live pages never go network-idle)
    const found = await overflow(page);
    if (found.length) problems[path] = found;
  }
  expect(problems).toEqual({});

  // the user menu, the notification panel and the assignee list stay on the screen
  const onScreen = async (locator: ReturnType<Page["locator"]>) => {
    const box = (await locator.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(280 + 1);
  };
  await page.goto("/projects");
  await page.getByRole("button", { name: /Root Admin/ }).click();
  await onScreen(page.getByRole("menu"));
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Notifications" }).click();
  await onScreen(page.getByRole("dialog", { name: "Notifications" }));
  await page.keyboard.press("Escape");
  await page.goto("/projects/MOB/tasks/1");
  await page.getByRole("combobox", { name: "Assignee" }).click();
  await onScreen(page.getByRole("listbox"));
  await page.keyboard.press("Escape");

  // long titles wrap rather than being cut or squeezed out
  await page.goto("/projects/MOB/backlog");
  const row = page.getByRole("button", { name: /A task with a rather long title/ });
  await expect(row).toBeVisible();
  expect((await row.boundingBox())!.width).toBeGreaterThan(150);
  await page.goto("/projects/MOB/tasks/1");
  const title = page.getByRole("textbox", { name: "Title" });
  await expect(title).toHaveValue(/must wrap on a narrow phone screen/);
  expect(await title.evaluate((el) => el.scrollHeight <= el.clientHeight + 1 && el.scrollWidth <= el.clientWidth + 1)).toBe(true);
});
