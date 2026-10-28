"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { api } from "@/lib/api";
import { kbKeys, type KbDocRef } from "@/lib/kb";

/** Knowledge Base documents (that the viewer can open) linking to this task with [[KEY-N]]. */
export function KbReferences({ taskKey }: { taskKey: string }) {
  const refs = useQuery({
    queryKey: kbKeys.refs(taskKey),
    queryFn: () => api<KbDocRef[]>(`/api/tasks/${taskKey}/kb-references`),
  });
  if (!refs.data?.length) return null;
  return (
    <section className="space-y-2">
      <h3 className="text-[11px] tracking-widest text-muted-foreground uppercase">Referenced in Knowledge Base</h3>
      <ul className="space-y-1 text-sm">
        {refs.data.map((r) => (
          <li key={r.id} className="flex flex-wrap items-baseline gap-2">
            <Link href={`/kb/doc/${r.id}`}>{r.title}</Link>
            <span className="text-xs text-muted-foreground">{r.space.name}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
