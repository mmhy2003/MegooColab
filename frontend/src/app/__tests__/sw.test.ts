import { readFileSync } from "node:fs";
import { join } from "node:path";
import { runInNewContext } from "node:vm";

import { describe, expect, it, vi } from "vitest";

const ORIGIN = "https://megoo.example.com";
const LINK = "/projects/PAY/board?task=PAY-1";

type Handler = (event: Record<string, unknown>) => void;

/** public/sw.js run in a sandbox that stands in for the service worker's global scope. */
function loadWorker(windows: { url: string; focus: () => Promise<unknown>; navigate: (u: string) => Promise<unknown> }[] = []) {
  const handlers: Record<string, Handler> = {};
  const self = {
    addEventListener: (type: string, fn: Handler) => (handlers[type] = fn),
    registration: { showNotification: vi.fn(async () => undefined) },
    clients: {
      matchAll: vi.fn(async () => windows),
      openWindow: vi.fn(async () => undefined),
      claim: vi.fn(async () => undefined),
    },
    location: { origin: ORIGIN },
    skipWaiting: vi.fn(async () => undefined),
  };
  runInNewContext(readFileSync(join(process.cwd(), "public", "sw.js"), "utf-8"), { self, caches: {}, URL, fetch, console });
  return { handlers, self };
}

/** Dispatches an event and waits for what the worker passed to waitUntil. */
async function fire(handler: Handler, event: Record<string, unknown>) {
  let waited: Promise<unknown> = Promise.resolve();
  handler({ ...event, waitUntil: (p: Promise<unknown>) => (waited = p) });
  await waited;
}

describe("service worker push", () => {
  it("shows the push", async () => {
    const { handlers, self } = loadWorker();
    await fire(handlers.push, { data: { json: () => ({ title: "PAY-1: t", body: "b", link: LINK }) } });
    expect(self.registration.showNotification).toHaveBeenCalledWith("PAY-1: t", {
      body: "b",
      icon: "/icons/icon-192.png",
      tag: LINK,
      data: { link: LINK },
    });
  });

  it("focuses an open window on click", async () => {
    const win = { url: `${ORIGIN}/dashboard`, focus: vi.fn(async () => undefined), navigate: vi.fn(async () => undefined) };
    const { handlers, self } = loadWorker([win]);
    const close = vi.fn();
    await fire(handlers.notificationclick, { notification: { close, data: { link: LINK } } });
    expect(close).toHaveBeenCalled();
    expect(win.navigate).toHaveBeenCalledWith(`${ORIGIN}${LINK}`);
    expect(win.focus).toHaveBeenCalled();
    expect(self.clients.openWindow).not.toHaveBeenCalled();
  });

  it("opens a window when none is open", async () => {
    const { handlers, self } = loadWorker();
    await fire(handlers.notificationclick, { notification: { close: vi.fn(), data: { link: LINK } } });
    expect(self.clients.openWindow).toHaveBeenCalledWith(LINK);
  });
});
