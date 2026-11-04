"use client";

import { FilePen } from "lucide-react";
import Link from "next/link";

import { draftTitle, useKbDrafts } from "@/lib/kbDrafts";

/** The person's unsaved drafts written with an agent, newest activity first. */
export function MyDrafts() {
  const drafts = useKbDrafts();
  if (!drafts.data?.length) return null;
  return (
    <section className="mb-6">
      <h2 className="mb-2 text-xs tracking-widest text-muted-foreground uppercase">My drafts</h2>
      <ul className="grid grid-cols-[minmax(0,1fr)] gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {drafts.data.map((d) => (
          <li key={d.id}>
            <Link href={`/kb/drafts/${d.id}`} className="card flex min-w-0 items-start gap-2 p-3 text-fg no-underline hover:glow-box">
              <FilePen size={16} aria-hidden className="mt-0.5 shrink-0 text-cyan-ink" />
              <span className="min-w-0">
                <span className="block truncate text-sm">{draftTitle(d.title)}</span>
                <span className="block truncate text-xs text-muted-foreground">
                  {d.space.name}
                  {d.agent ? ` · with ${d.agent.name}` : ""} · {new Date(d.last_activity_at).toLocaleString()}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
