import { expect, test, type Page } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";

/**
 * Passkeys as the second sign-in step, with Chromium's virtual authenticator: added on the profile, used after the
 * password, and turned off by an admin. Creates the user passkey@acme.io, so it needs a fresh stack.
 */

const WEB = { "X-Megoo-Client": "web" };
const MEMBER = { name: "Pat Passkey", email: "passkey@acme.io", temporary: "temporary-pass-1", password: "member-pass-123" };
const HOME = /^https?:\/\/[^/]+\/$/;

async function signOut(page: Page) {
  await page.getByRole("button", { name: MEMBER.name }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
}

test("a passkey from adding it to signing in with it, then an admin turns two-factor off", async ({ browser }) => {
  const adminCtx = await browser.newContext();
  const admin = await adminCtx.newPage();
  await setupOrSignIn(admin);
  const created = await admin.request.post("/api/admin/users", {
    data: { email: MEMBER.email, name: MEMBER.name, role: "member", temporary_password: MEMBER.temporary },
    headers: WEB,
  });
  expect(created.ok(), await created.text()).toBeTruthy();

  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: {
      protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true,
      isUserVerified: true, automaticPresenceSimulation: true,
    },
  });
  expect((await page.request.post("/api/auth/login", { data: { email: MEMBER.email, password: MEMBER.temporary }, headers: WEB })).ok()).toBeTruthy();
  expect((await page.request.post("/api/auth/change-password", {
    data: { current_password: MEMBER.temporary, new_password: MEMBER.password }, headers: WEB,
  })).ok()).toBeTruthy();
  // the password change signed this browser out: in again with the new one
  expect((await page.request.post("/api/auth/login", { data: { email: MEMBER.email, password: MEMBER.password }, headers: WEB })).ok()).toBeTruthy();

  // 1. add a passkey on the profile
  await page.goto("/settings/profile?tab=two-factor");
  await expect(page.getByText("Two-factor sign-in is off.")).toBeVisible();
  await page.getByRole("button", { name: "Add a passkey" }).click();
  await page.getByLabel("Passkey name").fill("E2E key");
  await page.getByRole("button", { name: "Save passkey" }).click();
  await expect(page.getByText("E2E key")).toBeVisible();
  await expect(page.getByText("Two-factor sign-in is on.")).toBeVisible();

  // 2. sign out, then in: the password, then the passkey (the prompt opens by itself)
  await signOut(page);
  await page.getByLabel("Email").fill(MEMBER.email);
  await page.getByLabel("Password").fill(MEMBER.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(HOME);
  await page.goto("/settings/profile?tab=two-factor");
  await expect(page.getByText(/last used (?!never)/)).toBeVisible();

  // 3. an admin turns off the member's two-factor sign-in
  await admin.goto("/admin/users");
  const row = admin.getByRole("row").filter({ hasText: MEMBER.email });
  await expect(row).toContainText("1 passkey");
  await row.getByRole("button", { name: `Actions for ${MEMBER.name}` }).click();
  await admin.getByRole("menuitem", { name: "Turn off two-factor sign-in" }).click();
  await admin.getByRole("alertdialog").getByRole("button", { name: "Turn off" }).click();
  await expect(row).toContainText("Off");

  // 4. the password alone signs them in now (their account is remembered on this browser)
  await signOut(page);
  await page.getByRole("button", { name: new RegExp(`^${MEMBER.name}`) }).click();
  await page.getByLabel("Password").fill(MEMBER.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(HOME);
  await adminCtx.close();
  await ctx.close();
});
