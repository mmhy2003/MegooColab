"use client";

import Link from "next/link";

import { useKbDrafts } from "@/lib/kbDrafts";

/** On a document: the person's unsaved draft of it, written with an agent. */
export function DraftBanner({ documentId }: { documentId: string }) {
  const drafts = useKbDrafts();
  const draft = drafts.data?.find((d) => d.document_id === documentId);
  if (!draft) return null;
  return (
    <p className="rounded border border-cyan/60 px-3 py-2 text-sm">
      You have an unsaved draft{draft.agent ? ` with ${draft.agent.name}` : ""} ·{" "}
      <Link href={`/kb/drafts/${draft.id}`}>Open</Link>
    </p>
  );
}
