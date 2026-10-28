import { expect, test } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";

/** The installable app (PWA): manifest and service worker reachable before sign-in, an offline page. Any stack. */

test("installable, with an offline page", async ({ browser, page }) => {
  const anon = await browser.newContext();
  try {
    const manifest = await anon.request.get("/manifest.webmanifest");
    expect(manifest.ok()).toBeTruthy();
    const m = (await manifest.json()) as { name: string; display: string; icons: { src: string }[] };
    expect(m.name).toBe("MegooColab");
    expect(m.display).toBe("standalone");
    for (const icon of m.icons) expect((await anon.request.get(icon.src)).ok(), icon.src).toBeTruthy();
    const sw = await anon.request.get("/sw.js");
    expect(sw.ok()).toBeTruthy();
    expect(sw.headers()["content-type"]).toContain("javascript");
  } finally {
    await anon.close();
  }

  await setupOrSignIn(page);
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute("href", "/manifest.webmanifest");
  const active = await page.evaluate(async () => !!(await navigator.serviceWorker.ready).active);
  expect(active).toBe(true);
  await page.reload(); // the service worker now controls the page
  await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true);

  await page.context().setOffline(true);
  await page.goto("/teams");
  await expect(page.getByRole("heading", { name: "You're offline" })).toBeVisible();
  await page.context().setOffline(false);
  await page.getByRole("link", { name: "Try again" }).click();
  await expect(page).toHaveURL(/\/projects$/);
});
