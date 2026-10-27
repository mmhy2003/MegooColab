"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { qk } from "@/lib/queries";

type S = components["schemas"];

export type Hit = S["Hit"];
export type QuickResults = S["QuickOut"];
export type SearchResults = S["GlobalSearchOut"];
export type SearchKind = "task" | "document" | "project" | "team" | "person" | "agent" | "question";

export const KINDS: SearchKind[] = ["task", "document", "project", "team", "person", "agent", "question"];
export const KIND_LABELS: Record<SearchKind, string> = {
  task: "Tasks",
  document: "Documents",
  project: "Projects",
  team: "Teams",
  person: "People",
  agent: "Agents",
  question: "Questions",
};
export const STATUS_LABELS: Record<string, string> = { before: "To do", working: "In progress", review: "Review", done: "Done" };
export const UPDATED_LABELS: Record<string, string> = { "7d": "Last 7 days", "30d": "Last 30 days", "365d": "Last year" };
export const PAGE = 20;

const PRE = "";
const POST = "";

/** Split a highlighted string into plain and marked parts. A marker without its partner is dropped. */
export function highlight(text: string): { text: string; mark: boolean }[] {
  const parts: { text: string; mark: boolean }[] = [];
  const push = (t: string, mark: boolean) => {
    if (!t) return;
    const last = parts[parts.length - 1];
    if (last && last.mark === mark) last.text += t;
    else parts.push({ text: t, mark });
  };
  let rest = text;
  while (rest) {
    const start = rest.indexOf(PRE);
    const stray = rest.indexOf(POST);
    if (stray !== -1 && (start === -1 || stray < start)) {
      push(rest.slice(0, stray), false);
      rest = rest.slice(stray + 1);
      continue;
    }
    if (start === -1) {
      push(rest, false);
      break;
    }
    push(rest.slice(0, start), false);
    const end = rest.indexOf(POST, start + 1);
    if (end === -1) {
      push(rest.slice(start + 1), false);
      break;
    }
    push(rest.slice(start + 1, end), true);
    rest = rest.slice(end + 1);
  }
  return parts.length ? parts : [{ text: "", mark: false }];
}

/** The text without highlight markers (for titles, aria labels). */
export function plain(text: string): string {
  return text.replaceAll(PRE, "").replaceAll(POST, "");
}

export type SearchParams = {
  q: string;
  kind: string[];
  project: string[];
  status: string[];
  assignee: string[];
  type: string[];
  label: string[];
  updated: string | null;
  sort: "relevance" | "newest";
  offset: number;
  meaning: boolean;
};

const LISTS = ["kind", "project", "status", "assignee", "type", "label"] as const;

export function paramsFromUrl(sp: URLSearchParams): SearchParams {
  const offset = Number(sp.get("offset") ?? 0);
  const updated = sp.get("updated");
  return {
    q: sp.get("q") ?? "",
    kind: sp.getAll("kind"),
    project: sp.getAll("project"),
    status: sp.getAll("status"),
    assignee: sp.getAll("assignee"),
    type: sp.getAll("type"),
    label: sp.getAll("label"),
    updated: updated && updated in UPDATED_LABELS ? updated : null,
    sort: sp.get("sort") === "newest" ? "newest" : "relevance",
    offset: Number.isInteger(offset) && offset > 0 ? offset : 0,
    meaning: sp.get("meaning") === "true",
  };
}

export function paramsToUrl(p: SearchParams): string {
  const sp = new URLSearchParams({ q: p.q });
  for (const name of LISTS) for (const v of p[name]) sp.append(name, v);
  if (p.updated) sp.set("updated", p.updated);
  if (p.sort !== "relevance") sp.set("sort", p.sort);
  if (p.offset > 0) sp.set("offset", String(p.offset));
  if (p.meaning) sp.set("meaning", "true");
  return sp.toString();
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** As-you-type search: debounced, off for an empty box, keeping the last results while the next arrive. */
export function useQuickSearch(q: string) {
  const term = useDebounced(q.trim(), 120);
  return useQuery({
    queryKey: qk.searchQuick(term),
    queryFn: () => api<QuickResults>(`/api/search/quick?${new URLSearchParams({ q: term })}`),
    enabled: term.length > 0,
    placeholderData: keepPreviousData,
    retry: false,
  });
}

export function useSearch(p: SearchParams) {
  const qs = paramsToUrl(p);
  return useQuery({
    queryKey: qk.search(qs),
    queryFn: () => api<SearchResults>(`/api/search?${qs}`),
    enabled: p.q.trim().length > 0,
    placeholderData: keepPreviousData,
    retry: false,
  });
}
