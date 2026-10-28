"use client";

import Link from "next/link";
import { useState } from "react";

import { ENTITY_GROUPS, type MemEntity } from "@/lib/memory";

/** Memory entities grouped by kind, with how many conclusions the viewer can see about each. */
export function EntityList({ entities }: { entities: MemEntity[] }) {
  const [filter, setFilter] = useState("");
  const f = filter.trim().toLowerCase();
  const shown = entities.filter((e) => !f || e.name.toLowerCase().includes(f));
  return (
    <section className="space-y-4" aria-label="Entities">
      <input
        aria-label="Filter entities"
        placeholder="Filter…"
        className="w-full max-w-sm rounded border border-line bg-surface-2 px-3 py-2 text-sm text-fg focus:border-cyan focus:outline-none"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      {ENTITY_GROUPS.map(({ kind, label }) => {
        const group = shown.filter((e) => e.kind === kind);
        if (group.length === 0) return null;
        return (
          <div key={kind}>
            <h3 className="mb-2 text-xs tracking-widest text-muted uppercase">{label}</h3>
            <ul className="grid grid-cols-[minmax(0,1fr)] gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {group.map((e) => (
                <li key={e.id}>
                  <Link
                    href={`/memory/entity/${e.id}`}
                    className="card flex items-baseline justify-between gap-2 p-3 text-fg no-underline hover:glow-box"
                  >
                    <span className="min-w-0 truncate text-sm">{e.name}</span>
                    <span className="shrink-0 text-xs text-muted">
                      {e.conclusion_count === 1 ? "1 conclusion" : `${e.conclusion_count} conclusions`}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
      {shown.length === 0 && <p className="text-sm text-muted">Nothing matches.</p>}
    </section>
  );
}
