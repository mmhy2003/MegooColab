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
