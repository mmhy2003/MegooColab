import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type PushDevice = components["schemas"]["PushSubscriptionOut"];

/** What the device card shows for the browser it is open in. */
export type PushState = "unsupported" | "ios-install" | "blocked" | "off" | "on";

export const pushKeys = {
  all: ["push"] as const,
  subscriptions: () => ["push", "subscriptions"] as const,
  thisDevice: () => ["push", "this-device"] as const,
};

/** The server's VAPID key (base64url) as the bytes PushManager.subscribe wants. */
export function base64UrlToBytes(value: string): Uint8Array<ArrayBuffer> {
  const raw = atob(value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "="));
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

function isIos(): boolean {
  // iPadOS reports itself as a Mac; its touch screen gives it away
  return /iPhone|iPad|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
}

function installed(): boolean {
  return (navigator as Navigator & { standalone?: boolean }).standalone === true
    || (typeof matchMedia === "function" && matchMedia("(display-mode: standalone)").matches);
}

/** iOS allows push only for a web app added to the Home Screen and opened from there. */
export function pushSupport(): "supported" | "unsupported" | "ios-install" {
  const supported = "serviceWorker" in navigator && typeof PushManager !== "undefined" && typeof Notification !== "undefined";
  if (isIos() && !installed()) return "ios-install";
  return supported ? "supported" : "unsupported";
}

/** The service worker's registration, if there is one (`ready` would wait for ever: it registers only in production,
 * and a failed registration is silent). */
async function registration(): Promise<ServiceWorkerRegistration | null> {
  if (pushSupport() !== "supported") return null;
  return (await navigator.serviceWorker.getRegistration()) ?? null;
}

async function currentSubscription(): Promise<PushSubscription | null> {
  return (await (await registration())?.pushManager.getSubscription()) ?? null;
}

function sameKey(subscription: PushSubscription, key: Uint8Array<ArrayBuffer>): boolean {
  const used = subscription.options?.applicationServerKey;
  if (!used) return false;
  const bytes = new Uint8Array(used);
  return bytes.length === key.length && bytes.every((b, i) => b === key[i]);
}

export async function thisDeviceEndpoint(): Promise<string | null> {
  return (await currentSubscription())?.endpoint ?? null;
}

/** Asks the browser (only now, after the click), subscribes with the server's key and registers this device.
 * "off": the prompt was dismissed, so it can be asked again. */
export async function turnOnPush(): Promise<"on" | "off" | "blocked"> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return permission === "denied" ? "blocked" : "off";
  const worker = await registration();
  if (!worker) throw new Error("Push isn't ready in this browser yet. Reload the page and try again.");
  const key = base64UrlToBytes((await api<{ public_key: string }>("/api/push/key")).public_key);
  let subscription = await worker.pushManager.getSubscription();
  if (subscription && !sameKey(subscription, key)) {
    await subscription.unsubscribe(); // made with a key the server no longer has (SECRET_KEY changed): never delivered
    subscription = null;
  }
  subscription ??= await worker.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
  const { endpoint, keys } = subscription.toJSON() as { endpoint: string; keys: { p256dh: string; auth: string } };
  await api("/api/push/subscriptions", { method: "POST", json: { endpoint, keys } });
  return "on";
}

/** This device: stop the browser's subscription, then forget it on the server. */
export async function turnOffPush(id: string): Promise<void> {
  await (await currentSubscription())?.unsubscribe();
  await api(`/api/push/subscriptions/${id}`, { method: "DELETE" });
}

/** Signing out: this device stops getting this person's notifications. */
export async function forgetThisDevice(): Promise<void> {
  const subscription = await currentSubscription();
  if (!subscription) return;
  try {
    const devices = await api<PushDevice[]>("/api/push/subscriptions");
    const mine = devices.find((d) => d.endpoint === subscription.endpoint);
    if (mine) await api(`/api/push/subscriptions/${mine.id}`, { method: "DELETE" });
  } finally {
    // even when the server can't be asked: an unsubscribed endpoint answers 410, and the server drops the row
    await subscription.unsubscribe();
  }
}
