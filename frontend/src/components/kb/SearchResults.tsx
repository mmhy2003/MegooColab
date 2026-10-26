import Link from "next/link";
import type { ReactNode } from "react";

import type { KbSearchResult } from "@/lib/kb";

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Wraps query words in <mark>; the snippet stays plain text (React escapes it), never HTML. */
export function highlight(text: string, query: string): ReactNode[] {
  const terms = [...new Set(query.toLowerCase().match(/[\p{L}\p{N}_]+/gu) ?? [])].filter((t) => t.length > 1);
  if (terms.length === 0) return [text];
  const re = new RegExp(`(${terms.map(escapeRegExp).join("|")})`, "giu");
  return text.split(re).map((part, i) =>
    i % 2 === 1 ? (
      <mark key={i} className="rounded bg-amber/30 px-0.5 text-fg">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

export function SearchResults({ query, results }: { query: string; results: KbSearchResult }) {
  return (
    <div className="space-y-3">
      {!results.semantic && (
        <p className="rounded border border-line bg-surface-2 px-3 py-2 text-xs text-muted">
          Semantic search is off — an admin can configure an embeddings model. Results match words exactly.
        </p>
      )}
      {results.results.length === 0 ? (
        <p className="text-sm text-muted">No documents match.</p>
      ) : (
        <ol className="space-y-3">
          {results.results.map((r) => (
            <li key={r.document_id} className="card p-3">
              <div className="flex flex-wrap items-baseline gap-2">
                <Link href={`/kb/doc/${r.document_id}`} className="text-sm font-semibold">
                  {r.title}
                </Link>
                <span className="rounded border border-line px-1.5 text-[11px] text-muted">{r.space.name}</span>
                {r.path && <span className="font-mono text-xs text-muted">{r.path}</span>}
                <span className="ml-auto font-mono text-[11px] text-muted" title="Relevance score">
                  {r.score.toFixed(4)}
                </span>
              </div>
              {r.snippet && <p className="kb-prose mt-1 text-sm break-words text-muted">{highlight(r.snippet, query)}</p>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
