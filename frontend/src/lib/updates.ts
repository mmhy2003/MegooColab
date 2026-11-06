"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/queries";
import type { Updates } from "@/lib/types";

const QUARTER_HOUR = 15 * 60 * 1000;

/** The latest MegooColab and runner releases. The server checks GitHub every hour; the page asks the server every
 * 15 minutes, so a new release shows within about an hour and a quarter. */
export function useUpdates() {
  return useQuery({
    queryKey: qk.updates(),
    queryFn: () => api<Updates>("/api/updates"),
    staleTime: QUARTER_HOUR,
    refetchInterval: QUARTER_HOUR,
  });
}
