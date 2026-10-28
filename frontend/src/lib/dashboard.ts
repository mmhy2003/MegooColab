"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";

type S = components["schemas"];

export type Dashboard = S["DashboardOut"];
export type DashboardScope = Dashboard["scope"];
export type Numbers = S["Numbers"];
export type NeedItem = S["NeedItem"];
export type MyTask = S["MyTask"];
export type RunningItem = S["RunningItem"];
export type Queued = S["Queued"];
export type AgentItem = S["AgentItem"];
export type StageRow = S["StageRow"];
export type Stages = S["Stages"];
export type DayFinished = S["DayFinished"];
export type ProjectRow = S["ProjectRow"];
export type ActivityRow = S["ActivityRow"];
export type SystemOut = S["SystemOut"];

/** Live events refresh these through the realtime throttle (at most once every 2 s), never on their own. */
export const dashboardKeys = {
  all: ["dashboard"] as const,
  scope: (s: DashboardScope) => ["dashboard", s] as const,
  count: () => ["dashboard-count"] as const,
};

/** Admins also refetch every minute: the System lines (jobs, search, AI, memory) send no live events. */
export function useDashboard(scope: DashboardScope, isAdmin: boolean) {
  return useQuery({
    queryKey: dashboardKeys.scope(scope),
    queryFn: () => api<Dashboard>(`/api/dashboard?scope=${scope}`),
    refetchInterval: isAdmin ? 60_000 : false,
  });
}

/** The sidebar badge: what needs the viewer (the Mine scope). */
export function useDashboardCount() {
  return useQuery({
    queryKey: dashboardKeys.count(),
    queryFn: () => api<{ needs_you: number }>("/api/dashboard/count"),
  });
}

export const SCOPE_KEY = "megoo.dashboard.scope";
const SCOPES: DashboardScope[] = ["mine", "teams", "all"];

export function readScope(isAdmin: boolean): DashboardScope {
  let stored: string | null = null;
  try {
    stored = localStorage.getItem(SCOPE_KEY);
  } catch {
    // storage blocked (private mode, site data off): the default it is
  }
  const scope = SCOPES.find((s) => s === stored);
  return !scope || (scope === "all" && !isAdmin) ? "teams" : scope;
}

export function writeScope(scope: DashboardScope): void {
  try {
    localStorage.setItem(SCOPE_KEY, scope);
  } catch {
    // not remembered; the page still works
  }
}

/** "42 s", "12 m", "5 h", "2 d": how long something has waited or run. */
export function shortDuration(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} m`;
  if (s < 86_400) return `${Math.floor(s / 3600)} h`;
  return `${Math.floor(s / 86_400)} d`;
}

/** The board with the task's drawer open, the link format notifications use. */
export function taskLink(key: string): string {
  return `/projects/${key.slice(0, key.lastIndexOf("-"))}/board?task=${key}`;
}
