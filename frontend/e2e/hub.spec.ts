import { expect, test, type APIRequestContext } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";

/**
 * Tool Hub (plan 23): an MCP kept with its key, shared with a team without the key, taken as a copy that later
 * gets an update, and removed by an admin. Runs on a fresh stack.
 */

const WEB = { "X-Megoo-Client": "web" };
const SECRET = "e2e-secret-value-123456";
const TAKER = { name: "Hana Hub", email: "hana.hub@acme.io", password: "hana-password-1" };

async function post<T = unknown>(request: APIRequestContext, url: string, data?: unknown): Promise<T> {
  const r = await request.post(url, { data, headers: WEB });
  expect(r.ok(), `${url}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return (await r.json()) as T;
}

test("tool hub: add, share without the key, take a copy", async ({ page, browser, request }) => {
  await setupOrSignIn(page);
  const login = await request.post("/api/auth/login", { data: { email: "root@acme.io", password: "correct-horse-1" }, headers: WEB });
  expect(login.ok()).toBeTruthy();

  // someone to share with, in a team with the admin
  const invite = await post<{ invite_url: string }>(request, "/api/admin/users/invite", { email: TAKER.email, name: TAKER.name, role: "member" });
  const taker = await browser.newContext({ baseURL: new URL(page.url()).origin });
  await post(taker.request, "/api/auth/accept-invite", { token: invite.invite_url.split("/invite/")[1], password: TAKER.password });
  const takerMe = (await (await taker.request.get("/api/auth/me")).json()) as { user: { id: string } };
  const adminMe = (await (await request.get("/api/auth/me")).json()) as { user: { id: string } };
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Hub Team", description: "" });
  const members = await request.put(`/api/teams/${team.id}/members`, { data: { user_ids: [adminMe.user.id, takerMe.user.id] }, headers: WEB });
  expect(members.ok()).toBeTruthy();

  // 1. the admin adds an MCP with a secret header, sets the secret and shares it with the team
  await page.goto("/hub");
  await page.getByRole("link", { name: "Add MCP" }).click();
  await page.getByLabel("Name").fill("ctx-e2e");
  await page.getByLabel("Address").fill("https://mcp.example.com/mcp");
  await page.getByRole("button", { name: "Add header" }).click();
  await page.getByLabel("Header 1 name").fill("X-Key");
  await page.getByRole("checkbox", { name: "Header 1 is secret" }).check();
  await page.getByRole("button", { name: "Add MCP" }).click();
  await expect(page.getByRole("heading", { name: "Secrets" })).toBeVisible();
  await page.getByLabel("X-Key").fill(SECRET);
  await page.getByRole("button", { name: "Save secrets" }).click();
  await expect(page.getByText("Saved.")).toBeVisible();
  await page.getByRole("checkbox", { name: "Hub Team" }).check();
  await page.getByRole("button", { name: "Share" }).click();
  await expect(page.getByText("Saved.").last()).toBeVisible();

  // 2. the teammate sees it without the key, and takes a copy
  const tp = await taker.newPage();
  await tp.goto("/hub?tab=shared");
  await tp.getByRole("link", { name: /ctx-e2e/ }).click();
  await expect(tp.getByText("needs X-Key")).toBeVisible();
  expect(await tp.content()).not.toContain(SECRET);
  await tp.getByRole("button", { name: "Add to my library" }).click();
  await expect(tp.getByRole("heading", { name: "Copy" })).toBeVisible();
  await tp.goto("/hub");
  await expect(tp.getByText("key missing")).toBeVisible();

  // 3. the owner improves it: the copy offers the update
  await page.getByLabel("Description").fill("Reads the docs, better");
  await page.getByRole("button", { name: "Save setup" }).click();
  await tp.reload();
  await expect(tp.getByText("Update available")).toBeVisible();
  await tp.getByRole("link", { name: /ctx-e2e/ }).click();
  await tp.getByRole("button", { name: "Take update" }).click();
  await expect(tp.getByRole("button", { name: "Take update" })).toBeHidden();
  await expect(tp.getByText("Reads the docs, better").first()).toBeVisible();

  // 4. an admin removes it: the copy says so
  await page.goto("/admin/hub");
  await page.getByRole("button", { name: "Remove ctx-e2e" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Remove" }).click();
  await expect(page.getByText("Nothing is shared beyond its owner.")).toBeVisible();
  await tp.goto("/hub");
  await expect(tp.getByText("removed by an admin")).toBeVisible();
  await taker.close();
});
