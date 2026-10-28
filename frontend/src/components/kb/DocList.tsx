import { FileText } from "lucide-react";
import Link from "next/link";

import type { KbTreeDoc } from "@/lib/kb";

/** The documents directly inside one folder (or at the space's root). */
export function DocList({ documents, folderId }: { documents: KbTreeDoc[]; folderId: string | null }) {
  const here = documents.filter((d) => (d.folder_id ?? null) === folderId).sort((a, b) => a.title.localeCompare(b.title));
  if (here.length === 0) return <p className="text-sm text-muted-foreground">No documents here yet.</p>;
  return (
    <ul className="divide-y divide-line">
      {here.map((d) => (
        <li key={d.id} className="flex flex-wrap items-center gap-3 py-2">
          <Link href={`/kb/doc/${d.id}`} className="flex min-w-0 flex-1 items-center gap-2 text-sm">
            <FileText size={14} aria-hidden className="shrink-0 text-muted-foreground" />
            <span className="min-w-0 truncate">{d.title}</span>
          </Link>
          <span className="font-mono text-xs text-muted-foreground">rev {d.latest_revision}</span>
          <span className="text-xs text-muted-foreground">{new Date(d.updated_at).toLocaleDateString()}</span>
        </li>
      ))}
    </ul>
  );
}
