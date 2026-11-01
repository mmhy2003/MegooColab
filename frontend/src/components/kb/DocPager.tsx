"use client";

import Link from "next/link";

import { kbSiblings, useKbTree } from "@/lib/kb";

/** The documents before and after this one in its folder. */
export function DocPager({ spaceId, docId }: { spaceId: string; docId: string }) {
  const tree = useKbTree(spaceId);
  const { prev, next } = kbSiblings(tree.data?.documents ?? [], docId);
  if (!prev && !next) return null;
  return (
    <nav aria-label="Folder" className="flex flex-wrap justify-between gap-2 border-t border-line pt-3 text-sm">
      {prev ? <Link href={`/kb/doc/${prev.id}`}>← {prev.title}</Link> : <span />}
      {next && <Link href={`/kb/doc/${next.id}`}>{next.title} →</Link>}
    </nav>
  );
}
