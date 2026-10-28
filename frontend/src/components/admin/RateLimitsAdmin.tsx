"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { errorMessage } from "@/lib/errors";

type Status = components["schemas"]["RateLimitsOut"];
const KEY = ["admin", "rate-limits"] as const;

/** Admin → Settings: whether the rate limits are on. With Valkey down they are off (requests are let through). */
export function RateLimitsAdmin() {
  const status = useQuery({ queryKey: KEY, queryFn: () => api<Status>("/api/admin/rate-limits") });
  const s = status.data;
  return (
    <section aria-label="Rate limits" className="card space-y-2 p-4 text-sm">
      <h2 className="font-semibold">Rate limits</h2>
      {status.error && <p className="text-pink">{errorMessage(status.error)}</p>}
      {s && (
        <p className={s.working ? "text-cyan-ink" : "text-pink"}>
          {s.working ? "Working" : "Valkey is unreachable — limits are off"}
        </p>
      )}
    </section>
  );
}
