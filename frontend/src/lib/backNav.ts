"use client";

import { useMemo, useSyncExternalStore } from "react";

import { readStored, writeStored } from "@/lib/stored";

/** The places someone reads through, page after page: moving inside one keeps where they came from. */
export type Area = "kb-read" | "kb-search" | "memory-read";
export type Origin = { url: string; label: string };

type Visit = { url: string; label: string | null };
type NavState = { current: Visit | null; origins: Partial<Record<Area, Origin>> };

const KEY = "megoo.nav";
const listeners = new Set<() => void>();

export function areaOf(url: string): Area | null {
  const path = url.split(/[?#]/)[0];
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "kb") {
    if (parts[1] === "search") return "kb-search";
    if (parts[1] === "doc") return parts[2] ? "kb-read" : null;
    return parts[1] ? "kb-read" : null;
  }
  if (parts[0] === "memory" && parts[1] === "entity" && parts[2]) return "memory-read";
  return null;
}

function load(): NavState {
  return readStored<NavState>(KEY, "session") ?? { current: null, origins: {} };
}

/** Called on every address and every change of the page's name: arriving in an area from a page outside it records
 *  that page (with the name it had) as the area's origin. */
export function recordVisit(url: string, label: string | null): void {
  const state = load();
  const prev = state.current;
  if (prev && prev.url === url) {
    // a null replaces a name too: in the render that changes the address, the trail can still be the last page's
    if (label === prev.label) return;
    prev.label = label;
  } else {
    const area = areaOf(url);
    if (prev && area && area !== areaOf(prev.url) && prev.label) state.origins[area] = { url: prev.url, label: prev.label };
    state.current = { url, label };
  }
  writeStored(KEY, state, "session");
  listeners.forEach((l) => l());
}

export function originFor(area: Area): Origin | null {
  return load().origins[area] ?? null;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The area's origin, kept current as the recorder runs. */
export function useOrigin(area: Area): Origin | null {
  // a string snapshot is stable between renders while the origin is unchanged
  const raw = useSyncExternalStore(subscribe, () => JSON.stringify(originFor(area)), () => "null");
  return useMemo(() => JSON.parse(raw) as Origin | null, [raw]);
}
