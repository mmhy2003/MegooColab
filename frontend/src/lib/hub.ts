"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";

type S = components["schemas"];

export type HubTool = S["ToolOut"];
export type HubToolSummary = S["ToolSummary"];
export type HubAdminTool = S["AdminToolOut"];
export type HubFileText = S["ToolFileText"];
export type HubSpec = S["McpSpec"];
export type HubShelf = "mine" | "shared" | "everyone";

/** Every Tool Hub query starts with "hub", so one invalidation refreshes them all. */
export const hubKeys = {
  all: ["hub"] as const,
  shelf: (shelf: HubShelf, q: string) => ["hub", "shelf", shelf, q] as const,
  tool: (id: string) => ["hub", "tool", id] as const,
  file: (id: string, path: string) => ["hub", "file", id, path] as const,
  admin: (q: string) => ["hub", "admin", q] as const,
};

export function useHubShelf(shelf: HubShelf, q = "") {
  const params = new URLSearchParams({ shelf });
  if (q) params.set("q", q);
  return useQuery({
    queryKey: hubKeys.shelf(shelf, q),
    queryFn: () => api<HubToolSummary[]>(`/api/hub/tools?${params}`),
  });
}

export function useHubTool(id: string) {
  return useQuery({ queryKey: hubKeys.tool(id), queryFn: () => api<HubTool>(`/api/hub/tools/${id}`) });
}

export function useHubFile(id: string, path: string | null) {
  return useQuery({
    queryKey: hubKeys.file(id, path ?? ""),
    queryFn: () => api<HubFileText>(`/api/hub/tools/${id}/file?${new URLSearchParams({ path: path ?? "" })}`),
    enabled: path !== null,
  });
}

/** How a tool is shared, in a few words: Private, Everyone, or Shared: <teams and people>. */
export function sharingLabel(sharing: HubToolSummary["sharing"]): string | null {
  if (!sharing) return null;
  if (sharing.everyone) return "Everyone";
  const names = [...sharing.teams, ...sharing.users].map((x) => x.name);
  return names.length ? `Shared: ${names.join(", ")}` : "Private";
}
