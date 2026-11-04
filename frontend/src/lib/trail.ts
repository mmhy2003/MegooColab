"use client";

import { useEffect, useId, useMemo, useSyncExternalStore } from "react";

/** One step of the top bar's trail. A null label is still loading; a crumb without href is plain text. */
export type Crumb = { label: string | null; href?: string };
/** A page's trail; `backName` names the page in a Back link when its last crumb would read badly there. */
export type Trail = { crumbs: Crumb[]; backName?: string };

const SECTIONS: Record<string, string> = {
  projects: "Projects",
  chats: "Chats",
  questions: "Questions",
  kb: "Knowledge Base",
  memory: "Memory",
  hub: "Tool Hub",
  teams: "Teams",
  notifications: "Notifications",
  search: "Search",
  admin: "Admin",
  settings: "Settings",
};

const UNDER: Record<string, Record<string, string>> = {
  admin: {
    agents: "Agents", ai: "AI", audit: "Audit log", git: "Git", hub: "Tool Hub", methodology: "Methodology", settings: "Settings",
    users: "Users",
  },
  settings: { agents: "My agents", notifications: "Notifications", profile: "Profile", secrets: "Secrets", tokens: "Access tokens" },
  projects: { new: "New project" },
  kb: { search: "Search" },
  hub: { "new-mcp": "Add MCP", "new-skill": "Add skill" },
};

// addresses that only redirect: never a link
const NO_PAGE = new Set(["/admin", "/settings"]);
// segments that are only part of a longer address (/kb/doc/<id>, /memory/entity/<id>, /projects/<key>/tasks/<n>)
const PASS_THROUGH = [/^\/kb\/doc$/, /^\/memory\/entity$/, /^\/projects\/[^/]+\/tasks$/];

const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-/i;

/** The trail of a page that states none: the address's segments, named, never an ID. */
export function pathTrail(pathname: string): Crumb[] {
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length === 0) return [{ label: "Dashboard" }];
  const out: Crumb[] = [];
  parts.forEach((p, i) => {
    const href = `/${parts.slice(0, i + 1).join("/")}`;
    if (PASS_THROUGH.some((re) => re.test(href))) return;
    const raw = decodeURIComponent(p);
    let label: string | null;
    if (i === 0) label = SECTIONS[p] ?? raw;
    else if (UNDER[parts[0]]?.[p] && i === 1) label = UNDER[parts[0]][p];
    else if (ID.test(p) || (parts[0] === "projects" && i === 1)) label = null; // a project's key waits for its name
    else label = raw;
    out.push(NO_PAGE.has(href) ? { label } : { label, href });
  });
  const last = out[out.length - 1];
  if (last) out[out.length - 1] = { label: last.label };
  return out;
}

/** What a Back link calls the page: its backName, else its last crumb. */
export function backNameOf(trail: Trail): string | null {
  return trail.backName ?? trail.crumbs[trail.crumbs.length - 1]?.label ?? null;
}

// Every mounted page and record with its trail, as lib/title.ts keeps titles: a record (a task in the drawer) wins
// over the page under it, and among equals the latest wins.
type Entry = Trail & { record: boolean; seq: number };
const shown = new Map<string, Entry>();
const listeners = new Set<() => void>();
let top: Entry | undefined;
let seq = 0;

function recompute() {
  let next: Entry | undefined;
  for (const e of shown.values()) {
    if (!next || Number(e.record) > Number(next.record) || (e.record === next.record && e.seq > next.seq)) next = e;
  }
  top = next;
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function useEntry(record: boolean, crumbs: Crumb[], backName: string | undefined) {
  const id = useId();
  const key = JSON.stringify([crumbs, backName ?? null]);
  useEffect(() => {
    const [c, b] = JSON.parse(key) as [Crumb[], string | null];
    shown.set(id, { crumbs: c, backName: b ?? undefined, record, seq: shown.get(id)?.seq ?? ++seq });
    recompute();
  }, [id, key, record]);
  useEffect(
    () => () => {
      shown.delete(id);
      recompute();
    },
    [id],
  );
}

/** States this page's trail in the top bar while it shows. */
export function useTrail(crumbs: Crumb[], opts?: { backName?: string }): void {
  useEntry(false, crumbs, opts?.backName);
}

/** States the trail of a record shown over a page (a task in the drawer), above the page's own. */
export function useRecordTrail(crumbs: Crumb[], opts?: { backName?: string }): void {
  useEntry(true, crumbs, opts?.backName);
}

/** The trail the top bar shows: the top stated one, else the address's. */
export function useShownTrail(pathname: string): Trail {
  const entry = useSyncExternalStore(subscribe, () => top, () => undefined);
  return useMemo(
    () => (entry ? { crumbs: entry.crumbs, backName: entry.backName } : { crumbs: pathTrail(pathname) }),
    [entry, pathname],
  );
}
