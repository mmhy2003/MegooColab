import { expect, test } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";

/** The sign-in page remembers the accounts signed in on this browser. Works on any stack (fresh or not). */

test("a remembered account signs in with its password alone, and × forgets it", async ({ browser }) => {
  const setup = await browser.newContext();
  await setupOrSignIn(await setup.newPage()); // the organization exists; this context is thrown away
  await setup.close();

  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto("/login");
  // nothing remembered yet: the form
  await page.getByLabel("Email").fill(ADMIN.email);
  await page.getByLabel("Password").fill(ADMIN.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/^https?:\/\/[^/]+\/$/);

  // sign out: the account stays in the list
  await page.getByRole("button", { name: ADMIN.name }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Choose an account" })).toBeVisible();
  await expect(page.getByLabel("Email")).toHaveCount(0);

  await page.getByRole("button", { name: new RegExp(`^${ADMIN.name}`) }).click();
  await expect(page.getByText(ADMIN.email)).toBeVisible();
  await page.getByLabel("Password").fill(ADMIN.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/^https?:\/\/[^/]+\/$/);

  await page.getByRole("button", { name: ADMIN.name }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await page.getByRole("button", { name: `Forget ${ADMIN.email} on this browser` }).click();
  await expect(page.getByLabel("Email")).toBeVisible();
  await ctx.close();
});
