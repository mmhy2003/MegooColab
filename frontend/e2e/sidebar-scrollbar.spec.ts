import { expect, test } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";

/** The collapsed rail's menu scrollbar. Works on any stack (fresh or not). */

// headless Chromium hides scrollbars by default, so they take no room; this file needs them as a real browser draws them
test.use({ launchOptions: { ignoreDefaultArgs: ["--hide-scrollbars"] } });

test("on the closed rail the menu's scrollbar doesn't cut into the icons; it comes back as the rail opens", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 360 }); // short, so the menu scrolls
  await setupOrSignIn(page);
  await page.goto("/projects");
  const nav = page.getByRole("navigation", { name: "Main" });
  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  await page.mouse.move(800, 200); // away from the rail
  await expect.poll(async () => (await nav.boundingBox())!.width).toBeLessThan(60);
  const fit = () =>
    nav.locator(".overflow-y-auto").evaluate((el: HTMLElement) => {
      const right = el.getBoundingClientRect().left + el.clientWidth; // the edge of what the scrollbar leaves visible
      // the icons, and any count or dot on their corner
      const icons = [...el.querySelectorAll("a > span.relative > *")].map((s) => s.getBoundingClientRect().right);
      return { scrolls: el.scrollHeight > el.clientHeight, bar: el.offsetWidth - el.clientWidth, cut: icons.filter((r) => r > right).length };
    });
  const closed = await fit();
  expect(closed.scrolls).toBe(true);
  expect(closed.bar).toBe(0);
  expect(closed.cut).toBe(0);

  await nav.getByRole("link", { name: "Teams" }).hover(); // the rail opens, and the scrollbar is back
  await expect.poll(async () => (await fit()).bar).toBeGreaterThan(0);
});
