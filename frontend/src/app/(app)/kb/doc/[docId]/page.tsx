"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { DocEditor } from "@/components/kb/DocEditor";
import { DocPager } from "@/components/kb/DocPager";
import { KbReader } from "@/components/kb/KbReader";
import { DocView } from "@/components/kb/DocView";
import { RevisionHistory } from "@/components/kb/RevisionHistory";
import { NotFoundView } from "@/components/shell/NotFound";
import { errorMessage, isNotFound } from "@/lib/errors";
import { cachedTreeDoc, useKbDocument } from "@/lib/kb";
import { usePageTitle } from "@/lib/title";

export default function KbDocumentPage() {
  const { docId } = useParams<{ docId: string }>();
  const router = useRouter();
  const search = useSearchParams();
  const editing = search.get("edit") === "1";
  const client = useQueryClient();
  const doc = useKbDocument(docId);
  usePageTitle(doc.data?.title, "Knowledge Base");
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
  if (!doc.data) {
    // opened from the tree or the pager: the tree stays while the document loads
    const seen = cachedTreeDoc(client, docId);
    const loading = <p className="text-sm text-muted-foreground">Loading…</p>;
    if (!seen) return loading;
    return (
      <KbReader spaceId={seen.spaceId} folderId={seen.folderId} docId={docId} docTitle={seen.title}>
        {loading}
      </KbReader>
    );
  }
  const d = doc.data;

  return (
    <KbReader spaceId={d.space.id} folderId={d.folder_id} docId={d.id} docTitle={d.title} editing={editing && d.can_write}>
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
          <DocPager spaceId={d.space.id} docId={d.id} />
        </>
      )}
    </KbReader>
  );
}
