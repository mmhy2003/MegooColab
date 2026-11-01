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
export type HubMachine = S["HubMachineOut"];
export type HubMachineTool = S["HubMachineTool"];
export type HubScan = S["ScanOut"];
export type HubImportItem = S["ImportItem"];
export type HubMachineState = NonNullable<S["HubProgramState"]["state"]>;

/** Every Tool Hub query starts with "hub", so one invalidation refreshes them all. */
export const hubKeys = {
  all: ["hub"] as const,
  shelf: (shelf: HubShelf, q: string) => ["hub", "shelf", shelf, q] as const,
  tool: (id: string) => ["hub", "tool", id] as const,
  file: (id: string, path: string) => ["hub", "file", id, path] as const,
  admin: (q: string) => ["hub", "admin", q] as const,
  machines: () => ["hub", "machines"] as const,
  summary: () => ["hub", "summary"] as const,
  prefs: () => ["hub", "prefs"] as const,
  scan: (id: string) => ["hub", "scan", id] as const,
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

export function useHubMachines() {
  return useQuery({ queryKey: hubKeys.machines(), queryFn: () => api<HubMachine[]>("/api/hub/machines") });
}

/** Whether any of my machines doesn't match my library: the sidebar's mark. */
export function useHubSummary() {
  return useQuery({
    queryKey: hubKeys.summary(),
    queryFn: () => api<{ out_of_step: boolean }>("/api/hub/machines/summary"),
    refetchInterval: 60_000,
  });
}

export function useHubPrefs() {
  return useQuery({ queryKey: hubKeys.prefs(), queryFn: () => api<{ auto_default: boolean }>("/api/hub/prefs") });
}

export const OS_LABEL: Record<string, string> = { windows: "Windows", linux: "Linux", macos: "macOS" };

/** A machine's state for one tool in one program, in words. */
export function stateText(state: HubMachineState, program: string, os: string | null | undefined, detail: string): string {
  switch (state) {
    case "installed": return "installed";
    case "update_ready": return "update ready";
    case "will_install": return "will install";
    case "will_remove": return "will remove";
    case "changed": return "changed on this machine";
    case "conflict": return "made by hand on this machine";
    case "key_missing": return "key missing: can't install yet";
    case "removed": return "push to uninstall";
    case "failed": return `failed: ${detail}`;
    case "not_supported": return `not supported by ${program}`;
    case "not_available": return `not available on ${(os && OS_LABEL[os]) || os || "this system"}`;
    case "waiting": return "waiting for the machine to come online";
  }
}
