import { expect, test } from "@playwright/test";

import { ADMIN, setupOrSignIn } from "./helpers/auth";

/**
 * Plan 10: the sign-in limit. The stack's env file sets CLIENT_IP_HEADER=X-Real-IP, so this test is its own visitor
 * (a random address each run): the other specs on the stack are never limited, and the test can run again at once.
 */

const WEB = { "X-Megoo-Client": "web" };

test("thirty failed sign-ins from one address, then try again later", async ({ browser, page }) => {
  await setupOrSignIn(page); // a set-up organization, signed in from the ordinary address

  const visitor = `203.0.113.${1 + Math.floor(Math.random() * 254)}`;
  const ctx = await browser.newContext({ extraHTTPHeaders: { "X-Real-IP": visitor } });
  try {
    for (let i = 0; i < 30; i++) {
      const r = await ctx.request.post("/api/auth/login", { data: { email: "nobody@acme.io", password: "wrong" }, headers: WEB });
      expect(r.status(), `attempt ${i + 1}`).toBe(401);
    }
    const blocked = await ctx.request.post("/api/auth/login", { data: { email: ADMIN.email, password: ADMIN.password }, headers: WEB });
    expect(blocked.status()).toBe(429);
    const body = (await blocked.json()) as { detail: string; retry_after: number };
    expect(body.detail).toBe("rate_limited");
    expect(body.retry_after).toBeGreaterThan(0);
    expect(blocked.headers()["retry-after"]).toBe(String(body.retry_after));

    // the sign-in page says when to try again
    const blockedPage = await ctx.newPage();
    await blockedPage.goto("/login");
    await blockedPage.getByLabel("Email").fill(ADMIN.email);
    await blockedPage.getByLabel("Password").fill(ADMIN.password);
    await blockedPage.getByRole("button", { name: /sign in/i }).click();
    await expect(blockedPage.getByText(/Too many attempts\. Try again in (\d+ minutes?|\d+ seconds?)\./)).toBeVisible();
  } finally {
    await ctx.close();
  }

  // another address still signs in
  const other = await browser.newContext();
  try {
    const r = await other.request.post("/api/auth/login", { data: { email: ADMIN.email, password: ADMIN.password }, headers: WEB });
    expect(r.status()).toBe(200);
  } finally {
    await other.close();
  }
});
