"use client";

import Link from "next/link";
import { useState } from "react";

import type { Crumb } from "@/lib/trail";

function CrumbItem({ crumb, last }: { crumb: Crumb; last: boolean }) {
  if (crumb.label === null) {
    return (
      <span aria-label="Loading" className="inline-block animate-pulse">
        …
      </span>
    );
  }
  if (last || !crumb.href) return <span className={last ? "text-fg" : undefined}>{crumb.label}</span>;
  return (
    <Link href={crumb.href} className="text-muted-foreground no-underline hover:text-cyan-ink">
      {crumb.label}
    </Link>
  );
}

function Crumbs({ crumbs }: { crumbs: Crumb[] }) {
  return crumbs.map((c, i) => (
    <span key={i}>
      {i > 0 && <span className="mx-1">/</span>}
      <CrumbItem crumb={c} last={i === crumbs.length - 1} />
    </span>
  ));
}

/** The top bar's trail. On a narrow screen a trail of more than three crumbs keeps its first and last, with the
 *  ones between behind "…". */
export function TrailNav({ crumbs }: { crumbs: Crumb[] }) {
  // shown in full for this trail only: the next page's long trail folds again
  const sig = JSON.stringify(crumbs);
  const [expandedFor, setExpandedFor] = useState<string | null>(null);
  const expanded = expandedFor === sig;
  const long = crumbs.length > 3;
  return (
    <nav aria-label="Breadcrumb" className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
      <span data-full className={long ? "hidden sm:inline" : undefined}>
        <Crumbs crumbs={crumbs} />
      </span>
      {long && (
        <span data-compact className="sm:hidden">
          {expanded ? (
            <Crumbs crumbs={crumbs} />
          ) : (
            <>
              <CrumbItem crumb={crumbs[0]} last={false} />
              <span className="mx-1">/</span>
              <button type="button" aria-label="Show full path" className="hover:text-cyan-ink" onClick={() => setExpandedFor(sig)}>
                …
              </button>
              <span className="mx-1">/</span>
              <CrumbItem crumb={crumbs[crumbs.length - 1]} last />
            </>
          )}
        </span>
      )}
    </nav>
  );
}
