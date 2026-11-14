import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";

/**
 * A card dragged out of a long column lands in the column it is let go over, wherever in that column: not only
 * near the middle of a column stretched as tall as the longest one. Project key DRG.
 */

const WEB = { "X-Megoo-Client": "web" };

async function post<T = unknown>(request: APIRequestContext, url: string, data: unknown): Promise<T> {
  const r = await request.post(url, { data, headers: WEB });
  expect(r.ok(), `${url}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return (await r.json().catch(() => null)) as T;
}

function column(page: Page, name: string) {
  return page.getByRole("region", { name: `${name} column` });
}

test("a card leaves a long column for wherever it is let go in the next one", async ({ page }) => {
  test.setTimeout(120_000);
  await setupOrSignIn(page);
  const request = page.request;
  const me = (await (await request.get("/api/auth/me")).json()) as { user: { id: string } };
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Drag Team", description: "" });
  const members = await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me.user.id] }, headers: WEB });
  expect(members.ok(), await members.text()).toBeTruthy();
  await post(request, "/api/projects", { key: "DRG", name: "Drag Demo", description: "", team_ids: [team.id] });
  expect((await request.patch("/api/projects/DRG", { data: { sprints_enabled: false }, headers: WEB })).ok()).toBeTruthy();
  for (let i = 1; i <= 25; i++) await post(request, "/api/projects/DRG/tasks", { title: `Card ${i}`, type: "task" });

  await page.goto("/projects/DRG/board");
  const card = column(page, "Backlog").getByRole("button", { name: /DRG-1 Card 1(?!\d)/ });
  await expect(card).toBeVisible();
  const target = column(page, "In Progress");
  const from = (await card.boundingBox())!;
  const to = (await target.boundingBox())!;
  expect(to.height).toBeGreaterThan(1_500); // as tall as Backlog: its middle is far below the screen
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + from.width / 2 + 20, from.y + from.height / 2, { steps: 5 });
  await page.mouse.move(to.x + to.width / 2, to.y + 150, { steps: 15 }); // near its top
  await page.mouse.up();
  await expect(target.getByText("Card 1", { exact: true })).toBeVisible();
  await expect(column(page, "Backlog").getByText("Card 1", { exact: true })).toHaveCount(0);
  await expect.poll(async () => {
    const task = (await (await request.get("/api/tasks/DRG-1")).json()) as { column_category: string };
    return task.column_category;
  }).toBe("working");
});
