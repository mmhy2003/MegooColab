"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { memKeys, type MemDreamRun } from "@/lib/memory";

function statsLine(stats: Record<string, unknown>): string {
  const n = (k: string) => Number(stats[k] ?? 0);
  const base = `${n("cards")} cards, ${n("replaced")} replaced, ${n("deduced")} deduced, ${n("induced")} induced`;
  const problems = [n("failed_pairs") && `${n("failed_pairs")} failed`, n("dropped") && `${n("dropped")} dropped`];
  return [base, ...problems.filter(Boolean)].join(", ");
}

/** Dreaming (MEM-4): recent consolidation runs and a manual trigger for admins. */
export function DreamPanel() {
  const client = useQueryClient();
  const runs = useQuery({ queryKey: memKeys.dreams(), queryFn: () => api<MemDreamRun[]>("/api/admin/memory/dreams") });
  const [error, setError] = useState<string | null>(null);
  return (
    <section className="card p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="font-display text-sm font-semibold tracking-wider uppercase">Dreaming</h2>
        <Button
          variant="ghost"
          onClick={async () => {
            setError(null);
            try {
              await api("/api/admin/memory/dream", { method: "POST" });
              await client.invalidateQueries({ queryKey: memKeys.dreams() });
            } catch (err) {
              setError(errorMessage(err));
            }
          }}
        >
          Dream now
        </Button>
      </div>
      <p className="mb-3 text-xs text-muted">
        The memory consolidates every night: it replaces outdated conclusions, deduces and induces new ones, and
        refreshes the summary cards.
      </p>
      {error && (
        <p role="alert" className="mb-2 text-sm text-pink">
          {error}
        </p>
      )}
      {runs.data?.length === 0 && <p className="text-sm text-muted">No dream runs yet.</p>}
      <ul className="divide-y divide-line text-sm">
        {(runs.data ?? []).map((r) => (
          <li key={r.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2">
            <span className="font-mono text-xs">{r.trigger}</span>
            <span className={r.status === "failed" ? "text-pink" : r.status === "running" ? "text-cyan-ink" : ""}>
              {r.status}
            </span>
            <span className="text-xs text-muted">
              {new Date(r.started_at).toLocaleString()}
              {r.finished_at ? ` → ${new Date(r.finished_at).toLocaleTimeString()}` : ""}
            </span>
            <span className="text-xs">{statsLine(r.stats)}</span>
            {r.error && <span className="text-xs text-pink">{r.error}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}
