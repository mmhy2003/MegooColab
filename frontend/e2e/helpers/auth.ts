import { expect, type Page } from "@playwright/test";

export const ADMIN = { name: "Root Admin", email: "root@acme.io", password: "correct-horse-1" };

/**
 * Gets the page signed in as the admin: runs first-run setup on a fresh install,
 * or just logs in when an earlier spec has already set the organization up.
 */
export async function setupOrSignIn(page: Page) {
  const status = await page.request.get("/api/setup/status");
  const fresh = (await status.json()).needs_setup === true;
  if (fresh) {
    await page.goto("/setup");
    await page.getByLabel("Organization name").fill("Acme");
    await page.getByLabel("Your name").fill(ADMIN.name);
    await page.getByLabel("Email").fill(ADMIN.email);
    await page.getByLabel("New password", { exact: true }).fill(ADMIN.password);
    await page.getByLabel("Confirm new password").fill(ADMIN.password);
    await page.getByRole("button", { name: "Create organization" }).click();
    await expect(page).toHaveURL(/\/projects$/);
    return;
  }
  const res = await page.request.post("/api/auth/login", {
    data: { email: ADMIN.email, password: ADMIN.password },
    headers: { "X-Megoo-Client": "web" },
  });
  expect(res.ok()).toBeTruthy();
  await page.goto("/projects");
  await expect(page).toHaveURL(/\/projects$/);
}
