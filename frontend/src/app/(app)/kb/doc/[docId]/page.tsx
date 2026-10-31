"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { DocEditor } from "@/components/kb/DocEditor";
import { DocView } from "@/components/kb/DocView";
import { RevisionHistory } from "@/components/kb/RevisionHistory";
import { NotFoundView } from "@/components/shell/NotFound";
import { errorMessage, isNotFound } from "@/lib/errors";
import { useKbDocument } from "@/lib/kb";

export default function KbDocumentPage() {
  const { docId } = useParams<{ docId: string }>();
  const router = useRouter();
  const search = useSearchParams();
  const editing = search.get("edit") === "1";
  const doc = useKbDocument(docId);
  const [tab, setTab] = useState<"document" | "history">("document");
  const setEditing = (on: boolean) => router.replace(on ? `/kb/doc/${docId}?edit=1` : `/kb/doc/${docId}`);

  // a failed refetch keeps the last data: an open editor (and its draft) must stay
  if (doc.isError && !doc.data) {
    if (isNotFound(doc.error)) return <NotFoundView />;
    return (
      <div className="card mx-auto mt-10 max-w-md p-6 text-center">
        <p className="text-pink">{errorMessage(doc.error)}</p>
        <Link href="/kb">Back to the Knowledge Base</Link>
      </div>
    );
  }
  if (!doc.data) return <p className="text-sm text-muted-foreground">Loading…</p>;
  const d = doc.data;

  return (
    <div className="space-y-4">
      <nav aria-label="Breadcrumb" className="text-sm">
        <Link href="/kb">Knowledge Base</Link> / <Link href={`/kb/${d.space.id}`}>{d.space.name}</Link>
      </nav>
      {doc.isError && (
        <p role="alert" className="rounded border border-pink/60 px-3 py-2 text-sm text-pink">
          This document is no longer available ({errorMessage(doc.error)}). Copy any text you want to keep.
        </p>
      )}
      {editing && d.can_write ? (
        <DocEditor doc={d} onSaved={() => setEditing(false)} onCancel={() => setEditing(false)} />
      ) : (
        <>
          <div role="tablist" aria-label="Document" className="flex gap-2 border-b border-line">
            {(["document", "history"] as const).map((t) => (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={tab === t}
                className={`px-3 py-1 text-sm capitalize ${tab === t ? "border-b-2 border-cyan text-cyan-ink" : "text-muted-foreground"}`}
                onClick={() => setTab(t)}
              >
                {t}
              </button>
            ))}
          </div>
          {tab === "document" ? <DocView doc={d} onEdit={() => setEditing(true)} /> : <RevisionHistory docId={d.id} />}
        </>
      )}
    </div>
  );
}
