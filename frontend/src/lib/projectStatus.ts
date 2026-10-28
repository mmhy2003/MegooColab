"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/queries";
import type { Project } from "@/lib/types";

export type ProjectStatus = Project["status"];

export const STATUS_LABEL: Record<ProjectStatus, string> = {
  active: "Active",
  finished: "Finished",
  archived: "Archived",
};

export const SHOW_ARCHIVED_KEY = "megoo.projects.showArchived";

/** Changing status works on a closed project too: it is how one is reopened. */
export function useSetProjectStatus(key: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (status: ProjectStatus) => api<Project>(`/api/projects/${key}/status`, { method: "PUT", json: { status } }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.project(key) });
      void client.invalidateQueries({ queryKey: qk.projects() });
    },
  });
}

export function readShowArchived(): boolean {
  try {
    return localStorage.getItem(SHOW_ARCHIVED_KEY) === "true";
  } catch {
    return false;
  }
}

export function writeShowArchived(show: boolean): void {
  try {
    localStorage.setItem(SHOW_ARCHIVED_KEY, String(show));
  } catch {
    // not remembered; the list still works
  }
}
