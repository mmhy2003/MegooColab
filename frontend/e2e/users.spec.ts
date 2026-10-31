import { expect, test, type APIRequestContext } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";

/**
 * Admin › Users: deleting an invited person and a real one; the real one's comment stays, without their name.
 * Creates the "Users Team" team, the USR project and the people below, so it needs a fresh stack.
 */

const WEB = { "X-Megoo-Client": "web" };
const GONE = { name: "Gil Gone", email: "gil.gone@acme.io", password: "temporary-pass-1" };
const INVITED = { name: "Ivy Invited", email: "ivy.invited@acme.io" };

async function post<T = unknown>(request: APIRequestContext, url: string, data: unknown): Promise<T> {
  const r = await request.post(url, { data, headers: WEB });
  expect(r.ok(), `${url}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return (await r.json()) as T;
}

test("an admin deletes an invited person and a real one; the team's work stays", async ({ page, browser }) => {
  await setupOrSignIn(page);
  const request = page.request;
  const me = (await (await request.get("/api/auth/me")).json()).user.id as string;
  const gone = (await post<{ user: { id: string } }>(request, "/api/admin/users", {
    email: GONE.email, name: GONE.name, role: "member", temporary_password: GONE.password,
  })).user;
  await post(request, "/api/admin/users/invite", { email: INVITED.email, name: INVITED.name, role: "member" });
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Users Team", description: "" });
  expect((await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [me, gone.id] }, headers: WEB })).ok()).toBeTruthy();
  await post(request, "/api/projects", { key: "USR", name: "Users", description: "", team_ids: [team.id] });
  const task = await post<{ key: string; number: number }>(request, "/api/projects/USR/tasks", { title: "Shared work", type: "task" });

  // Gil comments on the shared task
  const gilCtx = await browser.newContext();
  const gil = gilCtx.request;
  expect((await gil.post("/api/auth/login", { data: { email: GONE.email, password: GONE.password }, headers: WEB })).ok()).toBeTruthy();
  expect((await gil.post("/api/auth/change-password", { data: { current_password: GONE.password, new_password: "new-pass-12345" }, headers: WEB })).ok()).toBeTruthy();
  expect((await gil.post("/api/auth/login", { data: { email: GONE.email, password: "new-pass-12345" }, headers: WEB })).ok()).toBeTruthy();
  expect((await gil.post(`/api/tasks/${task.key}/comments`, { data: { body_md: "Gil was here" }, headers: WEB })).ok()).toBeTruthy();

  await page.goto("/admin/users");
  for (const person of [INVITED, GONE]) {
    const row = page.getByRole("row").filter({ hasText: person.email });
    await row.getByRole("button", { name: `Actions for ${person.name}` }).click();
    await page.getByRole("menuitem", { name: "Delete…" }).click();
    const dialog = page.getByRole("dialog", { name: `Delete ${person.name}?` });
    await expect(dialog.getByRole("button", { name: "Delete" })).toBeDisabled();
    await dialog.getByLabel(`Type ${person.email} to confirm`).fill(person.email);
    await dialog.getByRole("button", { name: "Delete" }).click();
    await expect(page.getByRole("row").filter({ hasText: person.email })).toHaveCount(0);
  }

  // Gil is signed out, and their comment stays on the task under "Someone"
  expect((await gil.get("/api/auth/me")).status()).toBe(401);
  await page.goto(`/projects/USR/tasks/${task.number}`);
  const comment = page.getByRole("listitem").filter({ hasText: "Gil was here" });
  await expect(comment).toContainText("Someone");
  await gilCtx.close();
});
