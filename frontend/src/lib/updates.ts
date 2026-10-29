"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/queries";
import type { Updates } from "@/lib/types";

const HOUR = 60 * 60 * 1000;

/** The latest MegooColab and runner releases (the server checks GitHub every 6 hours). */
export function useUpdates() {
  return useQuery({
    queryKey: qk.updates(),
    queryFn: () => api<Updates>("/api/updates"),
    staleTime: HOUR,
    refetchInterval: HOUR,
  });
}
