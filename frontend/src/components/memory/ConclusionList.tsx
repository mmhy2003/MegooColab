"use client";

import { useState } from "react";

import { ConclusionItem } from "@/components/memory/ConclusionItem";
import { Button } from "@/components/ui/Button";
import { errorMessage } from "@/lib/errors";
import { useMemConclusions, type ConclusionStatusFilter } from "@/lib/memory";

const FILTERS: { id: ConclusionStatusFilter; label: string }[] = [
  { id: "active", label: "Active" },
  { id: "superseded", label: "Superseded" },
  { id: "deleted", label: "Deleted" },
];

export function ConclusionList({ entityId }: { entityId: string }) {
  const [status, setStatus] = useState<ConclusionStatusFilter>("active");
  const pages = useMemConclusions(entityId, status);
  const items = (pages.data?.pages ?? []).flatMap((p) => p.items);
  return (
    <section aria-label="Conclusions" className="space-y-2">
      <div role="tablist" aria-label="Status" className="flex gap-2 border-b border-line">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            role="tab"
            aria-selected={status === f.id}
            className={`px-3 py-1 text-sm ${status === f.id ? "border-b-2 border-cyan text-cyan-ink" : "text-muted"}`}
            onClick={() => setStatus(f.id)}
          >
            {f.label}
          </button>
        ))}
      </div>
      {pages.error && <p className="text-sm text-pink">{errorMessage(pages.error)}</p>}
      {pages.data && items.length === 0 && <p className="text-sm text-muted">No conclusions here yet.</p>}
      <ul className="divide-y divide-line">
        {items.map((c) => (
          <ConclusionItem key={c.id} conclusion={c} />
        ))}
      </ul>
      {pages.hasNextPage && (
        <Button variant="ghost" disabled={pages.isFetchingNextPage} onClick={() => void pages.fetchNextPage()}>
          Load more
        </Button>
      )}
    </section>
  );
}
