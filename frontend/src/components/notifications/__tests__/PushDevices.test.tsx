import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PushDevices } from "@/components/notifications/PushDevices";
import { base64UrlToBytes } from "@/lib/push";

const THIS = "https://fcm.googleapis.com/fcm/send/this-device";
const OTHER = { id: "s2", endpoint: "https://web.push.apple.com/other", name: "Safari on iPhone", created_at: "2026-10-29T10:00:00Z" };
const CHROME_WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36";
const IPHONE_SAFARI = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";

type Env = {
  oldKey?: boolean;
  devices?: object[];
  permission?: NotificationPermission;
  grant?: NotificationPermission;
  subscribed?: boolean;
  push?: boolean;
  userAgent?: string;
};

/** A browser with (or without) push support, and the server's list of this person's devices. */
function setup({ oldKey = false, devices = [], permission = "default", grant = "granted", subscribed = false, push = true, userAgent = CHROME_WINDOWS }: Env = {}) {
  const calls: { method: string; url: string; body?: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ method: init?.method ?? "GET", url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (url === "/api/push/key") return new Response(JSON.stringify({ public_key: "BKey" }), { status: 200 });
    if (url === "/api/push/subscriptions" && !init?.method) return new Response(JSON.stringify(devices), { status: 200 });
    if (url === "/api/push/subscriptions") return new Response(JSON.stringify({ id: "s1", endpoint: THIS, name: "Chrome on Windows", created_at: "2026-10-30T10:00:00Z" }), { status: 201 });
    return new Response(null, { status: 204 });
  }));
  const subscription = {
    endpoint: THIS,
    // made with the server's current key, or (oldKey) with one the server no longer has
    options: { applicationServerKey: base64UrlToBytes(oldKey ? "OLDKEY" : "BKey").buffer },
    unsubscribe: vi.fn(async () => true),
    toJSON: () => ({ endpoint: THIS, keys: { p256dh: "p", auth: "a" } }),
  };
  const subscribe = vi.fn(async () => subscription);
  const requestPermission = vi.fn(async () => grant);
  vi.stubGlobal("navigator", { ...navigator, userAgent, maxTouchPoints: 0 });
  if (push) {
    const registration = { pushManager: { getSubscription: async () => (subscribed ? subscription : null), subscribe } };
    Object.defineProperty(navigator, "serviceWorker", {
      configurable: true,
      value: { ready: Promise.resolve(registration), getRegistration: async () => registration },
    });
    vi.stubGlobal("PushManager", function PushManager() {});
    vi.stubGlobal("Notification", { permission, requestPermission });
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PushDevices />
    </QueryClientProvider>,
  );
  return { calls, subscribe, requestPermission, subscription };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("PushDevices", () => {
  it("offers to turn push on, without asking the browser on load", async () => {
    const { requestPermission } = setup();
    expect(await screen.findByText("Push is off on this device")).toBeTruthy();
    expect(screen.getByText("Turn it on to get notifications here even when MegooColab is closed.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Turn on" })).toBeTruthy();
    expect(requestPermission).not.toHaveBeenCalled();
  });

  it("turns push on: permission, subscribe with the server key, register", async () => {
    const { calls, subscribe, requestPermission } = setup();
    await userEvent.click(await screen.findByRole("button", { name: "Turn on" }));
    expect(requestPermission).toHaveBeenCalled();
    await vi.waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(subscribe).toHaveBeenCalledWith({ userVisibleOnly: true, applicationServerKey: base64UrlToBytes("BKey") });
    expect(calls.find((c) => c.method === "POST")).toEqual({
      method: "POST", url: "/api/push/subscriptions", body: { endpoint: THIS, keys: { p256dh: "p", auth: "a" } },
    });
  });

  it("shows the blocked text when permission is refused", async () => {
    setup({ grant: "denied" });
    await userEvent.click(await screen.findByRole("button", { name: "Turn on" }));
    expect(await screen.findByText("Your browser blocks notifications from MegooColab. Allow them in this site's settings, then reload the page.")).toBeTruthy();
  });

  it("keeps Turn on when the permission prompt is just dismissed", async () => {
    setup({ grant: "default" });
    await userEvent.click(await screen.findByRole("button", { name: "Turn on" }));
    expect(await screen.findByRole("button", { name: "Turn on" })).toBeTruthy();
    expect(screen.getByText("Push is off on this device")).toBeTruthy();
    expect(screen.queryByText(/Your browser blocks notifications/)).toBeNull();
  });

  it("replaces a subscription made with an old server key", async () => {
    const { subscribe, subscription } = setup({ subscribed: true, oldKey: true, permission: "granted" });
    await userEvent.click(await screen.findByRole("button", { name: "Turn on" }));
    await vi.waitFor(() => expect(subscribe).toHaveBeenCalled());
    expect(subscription.unsubscribe).toHaveBeenCalled();
  });

  it("shows on, and turns off", async () => {
    const { calls, subscription } = setup({ permission: "granted", subscribed: true, devices: [{ id: "s1", endpoint: THIS, name: "Chrome on Windows", created_at: "2026-10-30T10:00:00Z" }] });
    expect(await screen.findByText("Push is on for this device")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Turn off" }));
    await vi.waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/push/subscriptions/s1")).toBe(true));
    expect(subscription.unsubscribe).toHaveBeenCalled();
  });

  it("lists the other devices with Remove", async () => {
    const { calls } = setup({ devices: [OTHER] });
    expect(await screen.findByText("Other devices getting push")).toBeTruthy();
    expect(screen.getByText(/^Safari on iPhone · since /)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Remove Safari on iPhone" }));
    await vi.waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/push/subscriptions/s2")).toBe(true));
  });

  it("says when the browser blocks notifications already", async () => {
    setup({ permission: "denied" });
    expect(await screen.findByText("Your browser blocks notifications from MegooColab. Allow them in this site's settings, then reload the page.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Turn on" })).toBeNull();
  });

  it("says when the browser can't receive push", async () => {
    setup({ push: false });
    expect(await screen.findByText("This browser can't receive push notifications.")).toBeTruthy();
  });

  it("tells iPhone users to add MegooColab to the Home Screen first", async () => {
    setup({ push: false, userAgent: IPHONE_SAFARI });
    expect(await screen.findByText("On iPhone and iPad, add MegooColab to your Home Screen (Share → Add to Home Screen) and open it from there to turn on push.")).toBeTruthy();
  });
});
