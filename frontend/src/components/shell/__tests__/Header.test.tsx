import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Header } from "@/components/shell/Header";
import type { User } from "@/lib/types";

vi.mock("next/navigation", () => ({ usePathname: () => "/projects", useRouter: () => ({ push: vi.fn() }) }));

const user = { id: "u1", name: "Ahmed", email: "a@x.io", role: "member" } as User;

beforeEach(() => {
  // the unread count, and an empty list of notifications
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => new Response(JSON.stringify(url.includes("unread-count") ? { count: 0 } : []), { status: 200 })),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderHeader() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Header user={user} onMenu={() => {}} />
    </QueryClientProvider>,
  );
}

describe("Header", () => {
  it("closes the user menu on a click outside it, with the page blurred while open", async () => {
    renderHeader();
    await userEvent.click(screen.getByRole("button", { name: /Ahmed/ }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.getAllByRole("menuitem").map((i) => i.textContent?.trim())).toEqual([
      "Profile", "Access tokens", "My agents", "Notifications", "Sign out",
    ]);
    await userEvent.click(document.querySelector("[data-backdrop]")!);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.querySelector("[data-backdrop]")).toBeNull();
  });

  it("works from the keyboard: arrows move, Escape closes and returns focus", async () => {
    renderHeader();
    const trigger = screen.getByRole("button", { name: /Ahmed/ });
    trigger.focus();
    await userEvent.keyboard("{Enter}");
    const items = screen.getAllByRole("menuitem");
    await userEvent.keyboard("{ArrowDown}");
    expect(items).toContain(document.activeElement);
    const first = document.activeElement;
    await userEvent.keyboard("{ArrowDown}");
    expect(document.activeElement).not.toBe(first);
    expect(items).toContain(document.activeElement);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("closes the notification panel on a click outside it and on Escape", async () => {
    renderHeader();
    const bell = screen.getByRole("button", { name: "Notifications" });
    await userEvent.click(bell);
    expect(screen.getByRole("dialog", { name: "Notifications" })).toBeInTheDocument();
    await userEvent.click(document.querySelector("[data-backdrop]")!);
    expect(screen.queryByRole("dialog", { name: "Notifications" })).toBeNull();
    await userEvent.click(bell);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Notifications" })).toBeNull();
  });

  it("opens the notification panel from the keyboard and gives focus back on Escape", async () => {
    renderHeader();
    const bell = screen.getByRole("button", { name: "Notifications" });
    bell.focus();
    await userEvent.keyboard("{Enter}");
    const panel = screen.getByRole("dialog", { name: "Notifications" });
    expect(panel).toBeInTheDocument();
    await userEvent.tab();
    expect(panel).toContainElement(document.activeElement as HTMLElement);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Notifications" })).toBeNull();
    expect(bell).toHaveFocus();
  });
});

describe("Header sign-out", () => {
  it("forgets this device's push subscription before signing out", async () => {
    const endpoint = "https://fcm.googleapis.com/fcm/send/this-device";
    const unsubscribe = vi.fn(async () => true);
    Object.defineProperty(navigator, "serviceWorker", {
      configurable: true,
      value: { getRegistration: async () => ({ pushManager: { getSubscription: async () => ({ endpoint, unsubscribe }) } }) },
    });
    vi.stubGlobal("PushManager", function PushManager() {});
    vi.stubGlobal("Notification", { permission: "granted" });
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url === "/api/push/subscriptions" && !init?.method) {
        return new Response(JSON.stringify([{ id: "s1", endpoint, name: "Chrome on Windows", created_at: "2026-10-30T10:00:00Z" }]), { status: 200 });
      }
      return new Response(JSON.stringify(url.includes("unread-count") ? { count: 0 } : []), { status: 200 });
    }));
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    renderHeader();
    await userEvent.click(screen.getByRole("button", { name: /Ahmed/ }));
    await userEvent.click(screen.getByRole("menuitem", { name: /Sign out/ }));
    await vi.waitFor(() => expect(assign).toHaveBeenCalledWith("/login"));
    expect(calls.indexOf("DELETE /api/push/subscriptions/s1")).toBeGreaterThan(-1);
    expect(calls.indexOf("DELETE /api/push/subscriptions/s1")).toBeLessThan(calls.indexOf("POST /api/auth/logout"));
    expect(unsubscribe).toHaveBeenCalled();
    Reflect.deleteProperty(navigator, "serviceWorker");
  });
});

describe("Header sign-out without push", () => {
  function signOutWith(serviceWorker: object, list: () => Response) {
    Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: serviceWorker });
    vi.stubGlobal("PushManager", function PushManager() {});
    vi.stubGlobal("Notification", { permission: "granted" });
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) =>
      url === "/api/push/subscriptions" && !init?.method
        ? list()
        : new Response(JSON.stringify(url.includes("unread-count") ? { count: 0 } : []), { status: 200 })));
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    return assign;
  }

  afterEach(() => Reflect.deleteProperty(navigator, "serviceWorker"));

  it("signs out when no service worker is registered (its ready never settles)", async () => {
    const assign = signOutWith({ getRegistration: async () => undefined, ready: new Promise(() => {}) }, () => new Response("[]"));
    renderHeader();
    await userEvent.click(screen.getByRole("button", { name: /Ahmed/ }));
    await userEvent.click(screen.getByRole("menuitem", { name: /Sign out/ }));
    await vi.waitFor(() => expect(assign).toHaveBeenCalledWith("/login"));
  });

  it("still unsubscribes this device when the server can't be asked", async () => {
    const unsubscribe = vi.fn(async () => true);
    const registration = { pushManager: { getSubscription: async () => ({ endpoint: "https://fcm.googleapis.com/x", unsubscribe }) } };
    const assign = signOutWith({ getRegistration: async () => registration }, () => new Response("down", { status: 500 }));
    renderHeader();
    await userEvent.click(screen.getByRole("button", { name: /Ahmed/ }));
    await userEvent.click(screen.getByRole("menuitem", { name: /Sign out/ }));
    await vi.waitFor(() => expect(assign).toHaveBeenCalledWith("/login"));
    expect(unsubscribe).toHaveBeenCalled();
  });
});
