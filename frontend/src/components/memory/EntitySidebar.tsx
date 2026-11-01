"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

import { ENTITY_GROUPS, useMemEntities } from "@/lib/memory";
import { useStoredState } from "@/lib/stored";

/** Memory's entities beside the one being read, grouped by kind, with the Memory page's filter. */
export function EntitySidebar({ currentId }: { currentId: string }) {
  const entities = useMemEntities();
  const [filter, setFilter] = useStoredState("memory.filter", "", "session");
  const currentRef = useRef<HTMLAnchorElement>(null);
  const f = filter.trim().toLowerCase();
  const shown = (entities.data ?? []).filter((e) => !f || e.name.toLowerCase().includes(f));
  const loaded = Boolean(entities.data);
  useEffect(() => {
    currentRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [currentId, loaded]);

  return (
    <div className="space-y-3">
      <input
        aria-label="Filter entities"
        placeholder="Filter…"
        className="w-full rounded border border-line bg-surface-2 px-2 py-1.5 text-sm text-fg focus:border-cyan focus:outline-none"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      {ENTITY_GROUPS.map(({ kind, label }) => {
        const group = shown.filter((e) => e.kind === kind);
        if (group.length === 0) return null;
        return (
          <div key={kind}>
            <h3 className="mb-1 text-xs tracking-widest text-muted-foreground uppercase">{label}</h3>
            <ul className="space-y-0.5">
              {group.map((e) => {
                const current = e.id === currentId;
                return (
                  <li key={e.id}>
                    <Link
                      ref={current ? currentRef : undefined}
                      href={`/memory/entity/${e.id}`}
                      aria-current={current ? "page" : undefined}
                      className={`flex items-baseline justify-between gap-2 rounded px-2 py-1 text-sm no-underline ${current ? "bg-surface-2 text-cyan-ink" : "text-fg"}`}
                    >
                      <span className="min-w-0 truncate">{e.name}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">{e.conclusion_count}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
      {loaded && shown.length === 0 && <p className="text-sm text-muted-foreground">Nothing matches.</p>}
    </div>
  );
}
