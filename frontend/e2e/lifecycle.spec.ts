import { expect, test, type APIRequestContext } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";

/**
 * End-to-end test of Plan 13, the project lifecycle: delete a sprint (its tasks go back to the backlog), finish a
 * project and see it read-only, reopen it, archive it out of the Projects list, then delete it by typing its key.
 * Creates the "Life Team" team and the LIF project, so it needs a fresh stack.
 */

const WEB = { "X-Megoo-Client": "web" };

async function post<T = unknown>(request: APIRequestContext, url: string, data: unknown): Promise<T> {
  const r = await request.post(url, { data, headers: WEB });
  expect(r.ok(), `${url}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return (await r.json()) as T;
}

test("project lifecycle: finish, reopen, archive, delete a sprint and a project", async ({ page }) => {
  await setupOrSignIn(page);
  const request = page.request;
  const me = (await (await request.get("/api/auth/me")).json()).user.id as string;
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Life Team", description: "" });
  expect((await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me] }, headers: WEB })).ok()).toBeTruthy();
  await post(request, "/api/projects", { key: "LIF", name: "Lifecycle", description: "", team_ids: [team.id] });
  const inSprint = await post<{ key: string }>(request, "/api/projects/LIF/tasks", { title: "Planned work", type: "task" });
  await post(request, "/api/projects/LIF/tasks", { title: "Loose work", type: "task" });
  const sprint = await post<{ id: string }>(request, "/api/projects/LIF/sprints", {
    name: "S1", start_date: "2026-11-02", end_date: "2026-11-13",
  });
  expect((await request.put(`/api/tasks/${inSprint.key}/sprint`, { data: { sprint_id: sprint.id }, headers: WEB })).ok()).toBeTruthy();

  // 1. delete the sprint: its task goes back to the backlog
  await page.goto("/projects/LIF/backlog");
  const s1 = page.getByRole("region", { name: /^S1/ });
  await expect(s1.getByText("Planned work")).toBeVisible();
  await page.getByRole("button", { name: "Delete sprint S1" }).click();
  const confirm = page.getByRole("alertdialog");
  await expect(confirm).toContainText("1 task goes back to the backlog.");
  await confirm.getByRole("button", { name: "Delete" }).click();
  const backlog = page.getByRole("region", { name: /^Backlog/ });
  await expect(backlog.getByText("Planned work")).toBeVisible();
  await expect(backlog.getByText("Loose work")).toBeVisible();

  // 2. finish the project: read-only, with the banner
  await page.goto("/projects/LIF/settings");
  await page.getByRole("button", { name: "Finished" }).click();
  await expect(page.getByRole("status").filter({ hasText: "This project is finished. It is read-only." })).toBeVisible();
  await page.goto("/projects/LIF/backlog");
  await page.getByLabel("New backlog item").fill("Too late");
  await page.getByLabel("New backlog item").press("Enter");
  await expect(page.getByRole("alert").filter({ hasText: "This project is closed" })).toHaveText(
    "This project is closed. Reopen it to make changes.",
  );

  // 3. reopen it: the banner goes, and creating works again
  await page.getByRole("button", { name: "Reopen" }).click();
  await expect(page.getByText("This project is finished. It is read-only.")).toHaveCount(0);
  await page.getByLabel("New backlog item").fill("Back at it");
  await page.getByLabel("New backlog item").press("Enter");
  await expect(page.getByText("Back at it")).toBeVisible();

  // 4. archive it: gone from the Projects list unless Show archived is on
  await page.goto("/projects/LIF/settings");
  await page.getByRole("button", { name: "Archived" }).click();
  await expect(page.getByText("This project is archived. It is read-only and hidden from lists.")).toBeVisible();
  await page.goto("/projects");
  await expect(page.getByRole("link", { name: /Lifecycle/ })).toHaveCount(0);
  await page.getByRole("checkbox", { name: "Show archived" }).check();
  await expect(page.getByRole("link", { name: /Lifecycle/ })).toBeVisible();

  // 5. delete it by typing its key
  await page.goto("/projects/LIF/settings");
  await page.getByRole("button", { name: "Delete project" }).click();
  const dialog = page.getByRole("dialog", { name: "Delete LIF?" });
  const remove = dialog.getByRole("button", { name: "Delete LIF for good" });
  await expect(remove).toBeDisabled();
  await dialog.getByLabel("Type LIF to confirm").fill("LIF");
  await remove.click();
  await expect(page).toHaveURL(/\/projects$/);
  expect((await request.get("/api/projects/LIF")).status()).toBe(404);
});
