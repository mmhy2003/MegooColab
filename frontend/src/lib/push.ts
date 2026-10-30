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

async function currentSubscription(): Promise<PushSubscription | null> {
  if (pushSupport() !== "supported") return null;
  const registration = await navigator.serviceWorker.ready;
  return registration.pushManager.getSubscription();
}

export async function thisDeviceEndpoint(): Promise<string | null> {
  return (await currentSubscription())?.endpoint ?? null;
}

/** Asks the browser (only now, after the click), subscribes with the server's key and registers this device. */
export async function turnOnPush(): Promise<"on" | "blocked"> {
  if ((await Notification.requestPermission()) !== "granted") return "blocked";
  const { public_key } = await api<{ public_key: string }>("/api/push/key");
  const registration = await navigator.serviceWorker.ready;
  const subscription =
    (await registration.pushManager.getSubscription())
    ?? (await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: base64UrlToBytes(public_key) }));
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
  const devices = await api<PushDevice[]>("/api/push/subscriptions");
  const mine = devices.find((d) => d.endpoint === subscription.endpoint);
  if (mine) await api(`/api/push/subscriptions/${mine.id}`, { method: "DELETE" });
  await subscription.unsubscribe();
}
