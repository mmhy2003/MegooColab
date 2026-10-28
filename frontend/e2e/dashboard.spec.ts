import { expect, test, type APIRequestContext } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";
import { tool } from "./helpers/mcp";

/**
 * End-to-end test of Plan 12, the dashboard: with the home page open, a connect-only design starts waiting for the
 * admin's approval (set up through the API and MCP); the Needs you row, the "Need you" number and the sidebar badge
 * update without a reload. Creates the "Dash Team" team and the DSH project, so it needs a fresh stack.
 */

const WEB = { "X-Megoo-Client": "web" };

async function post<T = unknown>(request: APIRequestContext, url: string, data: unknown): Promise<T> {
  const r = await request.post(url, { data, headers: WEB });
  expect(r.ok(), `${url}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return (await r.json()) as T;
}

test("dashboard: a design waiting for approval shows up live", async ({ page }) => {
  await setupOrSignIn(page);
  const request = page.request;
  const me = (await (await request.get("/api/auth/me")).json()).user.id as string;
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Dash Team", description: "" });
  const members = await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB });
  expect(members.ok()).toBeTruthy();
  await post(request, "/api/projects", { key: "DSH", name: "Dashboard demo", description: "", team_ids: [team.id] });
  const task = await post<{ key: string }>(request, "/api/projects/DSH/tasks", {
    title: "Design the dashboard copy",
    type: "task",
    assignee_user_id: me,
  });
  const token = await post<{ secret: string }>(request, "/api/tokens", { name: "Dashboard e2e", scopes: ["mcp"] });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  const needYou = page.getByRole("group", { name: "Need you" }).locator("p").first();
  await expect(needYou).toHaveText(/^\d+$/);
  const before = Number(await needYou.textContent());

  // the workflow is connect-only (the task is a person's): submitting a design makes it wait for the admin
  await tool(request, token.secret, "submit_design", { key: task.key, markdown: "# Copy\n\nShort words." });

  const needs = page.getByRole("region", { name: "Needs you" });
  const row = needs.getByRole("listitem").filter({ hasText: task.key });
  await expect(row).toContainText("Approve design", { timeout: 10_000 });
  await expect(needYou).toHaveText(String(before + 1));
  const badge = page.getByRole("navigation", { name: "Main" }).getByLabel(/ need you$/);
  await expect(badge).toBeVisible();
  expect(Number(await badge.textContent())).toBeGreaterThanOrEqual(1);

  await row.getByRole("link", { name: `Review ${task.key}` }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/DSH/board\\?task=${task.key}$`));
});
