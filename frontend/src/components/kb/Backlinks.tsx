"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { api } from "@/lib/api";
import { kbKeys, type KbDocRef } from "@/lib/kb";

/** Documents (that the reader can open) linking to this one. */
export function Backlinks({ docId }: { docId: string }) {
  const refs = useQuery({
    queryKey: kbKeys.backlinks(docId),
    queryFn: () => api<KbDocRef[]>(`/api/kb/documents/${docId}/backlinks`),
  });
  return (
    <section aria-label="Backlinks">
      <h2 className="mb-2 text-xs tracking-widest text-muted-foreground uppercase">Linked from</h2>
      {refs.data?.length === 0 && <p className="text-sm text-muted-foreground">No other documents link here.</p>}
      <ul className="space-y-1">
        {(refs.data ?? []).map((r) => (
          <li key={r.id} className="flex flex-wrap items-baseline gap-2 text-sm">
            <Link href={`/kb/doc/${r.id}`}>{r.title}</Link>
            <span className="text-xs text-muted-foreground">{r.space.name}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
