"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";

type S = components["schemas"];

export type Secret = S["SecretOut"];
export type OutdatedAgent = S["OutdatedAgent"];

/** An environment variable name: capital letters, digits and _, starting with a letter (the server's rule). */
export const SECRET_NAME = /^[A-Z][A-Z0-9_]{0,99}$/;
/** Shorter values can't be blanked out of what agents send back (the runner's and the server's rule). */
export const BLANKED_MIN = 4;

export const secretKeys = {
  list: (base: string) => ["secrets", base] as const,
  outdated: (project?: string) => ["secrets", "outdated", project ?? ""] as const,
};

export function useSecrets(base: string) {
  return useQuery({ queryKey: secretKeys.list(base), queryFn: () => api<Secret[]>(base) });
}

export function useOutdatedAgents(project?: string) {
  const query = project ? `?project=${encodeURIComponent(project)}` : "";
  return useQuery({
    queryKey: secretKeys.outdated(project),
    queryFn: () => api<OutdatedAgent[]>(`/api/secrets/outdated-agents${query}`),
  });
}
