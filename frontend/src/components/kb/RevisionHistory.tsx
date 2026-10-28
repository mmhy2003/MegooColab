"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { DiffView } from "@/components/kb/DiffView";
import { api } from "@/lib/api";
import { kbKeys, useKbRevisions, type DiffOp } from "@/lib/kb";

function who(author: { user?: { name: string } | null; agent?: { name: string } | null }): string {
  const user = author.user?.name ?? "Someone";
  return author.agent ? `${user} (via ${author.agent.name})` : user;
}

/** Every revision with its author; pick two to compare. */
export function RevisionHistory({ docId }: { docId: string }) {
  const revisions = useKbRevisions(docId);
  const [picked, setPicked] = useState<number[]>([]);
  const [a, b] = [...picked].sort((x, y) => x - y);
  const diff = useQuery({
    queryKey: kbKeys.diff(docId, a ?? 0, b ?? 0),
    queryFn: () => api<DiffOp[]>(`/api/kb/documents/${docId}/revisions/${a}/diff/${b}`),
    enabled: picked.length === 2,
  });

  const toggle = (n: number) =>
    setPicked((cur) => (cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n].slice(-2)));

  return (
    <section aria-label="History" className="space-y-3">
      <p className="text-sm text-muted-foreground">Pick two revisions to compare.</p>
      <ul className="divide-y divide-line">
        {(revisions.data ?? []).map((r) => (
          <li key={r.revision} className="flex flex-wrap items-center gap-3 py-2 text-sm">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={picked.includes(r.revision)} onChange={() => toggle(r.revision)} />
              <span className="font-mono">rev {r.revision}</span>
            </label>
            <span>{who(r.author)}</span>
            {r.summary && <span className="text-muted-foreground">— {r.summary}</span>}
            <span className="ml-auto text-xs text-muted-foreground">{new Date(r.created_at).toLocaleString()}</span>
          </li>
        ))}
      </ul>
      {picked.length === 2 && diff.data && (
        <div>
          <p className="mb-1 text-xs text-muted-foreground">
            Changes from rev {a} to rev {b}
          </p>
          <DiffView ops={diff.data} />
        </div>
      )}
    </section>
  );
}

export { who as revisionAuthor };
