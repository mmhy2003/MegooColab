import { expect, test } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";

/** The sidebar and the header bar stay in view while a long page scrolls. Works on any stack (fresh or not). */

test("the sidebar and the header stay put while the page scrolls", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 500 }); // short, so the settings page scrolls
  await setupOrSignIn(page);
  await page.goto("/admin/settings");
  const sidebar = page.getByRole("navigation", { name: "Main" });
  await expect(sidebar).toBeVisible();
  const scrolled = await page.evaluate(() => {
    window.scrollTo(0, document.body.scrollHeight);
    return window.scrollY;
  });
  expect(scrolled).toBeGreaterThan(200);
  await expect(sidebar.getByRole("link", { name: "MEGOOCOLAB" })).toBeInViewport();
  expect((await sidebar.boundingBox())!.y).toBe(0);
  const header = page.getByRole("banner");
  await expect(header.getByRole("button", { name: "Notifications" })).toBeInViewport();
  expect((await header.boundingBox())!.y).toBe(0);
});
