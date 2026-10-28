import { expect, test } from "@playwright/test";

import { setupOrSignIn } from "./helpers/auth";

/** The sidebar and the header bar stay in view while a long page scrolls. Works on any stack (fresh or not). */

test("the sidebar and the header stay put while the page scrolls", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 500 }); // short, so the settings page scrolls
  await setupOrSignIn(page);
  await page.goto("/admin/settings");
  const sidebar = page.getByRole("navigation", { name: "Main" });
  await expect(sidebar).toBeVisible();
  // poll: the settings load after the page does, and only then is there something to scroll
  await expect
    .poll(() =>
      page.evaluate(() => {
        window.scrollTo({ top: document.body.scrollHeight, behavior: "instant" });
        return window.scrollY;
      }),
    )
    .toBeGreaterThan(200);
  await expect(sidebar.getByRole("link", { name: "MEGOOCOLAB" })).toBeInViewport();
  expect((await sidebar.boundingBox())!.y).toBe(0);
  const header = page.getByRole("banner");
  await expect(header.getByRole("button", { name: "Notifications" })).toBeInViewport();
  expect((await header.boundingBox())!.y).toBe(0);
});

test("scrollbars stay hidden until the pointer is over the area, then show in cyan", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 400 }); // short, so the sidebar itself scrolls
  await setupOrSignIn(page);
  await page.goto("/projects");
  const aside = page.locator("aside").first();
  const colour = () => aside.evaluate((el) => getComputedStyle(el).scrollbarColor);
  const cyan = await page.evaluate(() => {
    const probe = document.createElement("i");
    probe.style.color = "var(--cyan)";
    document.body.append(probe);
    const c = getComputedStyle(probe).color;
    probe.remove();
    return c;
  });
  await page.mouse.move(900, 300); // over the page, not the sidebar
  expect(await colour()).toMatch(/^(transparent|rgba\(0, 0, 0, 0\)) /);
  expect(await aside.evaluate((el) => getComputedStyle(el).scrollbarWidth)).toBe("thin");
  await aside.hover();
  await expect.poll(colour).toContain(cyan); // it fades in over 0.2s
  // jumps within a page glide; Next.js keeps page-to-page navigation instant (data-scroll-behavior)
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior)).toBe("smooth");
  expect(await page.locator("html").getAttribute("data-scroll-behavior")).toBe("smooth");
});

test("checkboxes are on/off switches that light up cyan", async ({ page }) => {
  await setupOrSignIn(page);
  await page.goto("/admin/settings");
  const box = page.getByRole("checkbox", { name: "Require a human code review" });
  await expect(box).toBeVisible();
  const look = () =>
    box.evaluate((el) => {
      const s = getComputedStyle(el);
      const knob = getComputedStyle(el, "::after");
      return { appearance: s.appearance, width: s.width, radius: s.borderRadius, bg: s.backgroundColor, knob: knob.transform };
    });
  const cyan = await page.evaluate(() => {
    const probe = document.createElement("i");
    probe.style.color = "var(--cyan)";
    document.body.append(probe);
    const c = getComputedStyle(probe).color;
    probe.remove();
    return c;
  });
  if (await box.isChecked()) await box.uncheck();
  const off = await look();
  expect(off.appearance).toBe("none");
  expect(off.width).toBe("38px");
  expect(off.radius).toBe("999px");
  expect(off.bg).not.toBe(cyan);
  await box.check(); // still a real checkbox: role, label and keyboard all work
  await expect(box).toBeChecked();
  await expect.poll(async () => (await look()).bg).toBe(cyan); // it lights up over 0.2s
  await expect.poll(async () => (await look()).knob).not.toBe(off.knob); // the knob slides across
});
