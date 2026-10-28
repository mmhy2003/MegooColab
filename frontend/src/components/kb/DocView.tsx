"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Backlinks } from "@/components/kb/Backlinks";
import { KbMarkdown } from "@/components/kb/KbMarkdown";
import { revisionAuthor } from "@/components/kb/RevisionHistory";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { kbKeys, kbPath, useKbSpaces, type KbDocument } from "@/lib/kb";

/** A document: title, where it lives, who changed it last, the rendered body and what links to it. */
export function DocView({ doc, onEdit }: { doc: KbDocument; onEdit: () => void }) {
  const router = useRouter();
  const client = useQueryClient();
  const [moving, setMoving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    if (!confirm(`Delete "${doc.title}" and its history?`)) return;
    try {
      await api(`/api/kb/documents/${doc.id}`, { method: "DELETE" });
      await client.invalidateQueries({ queryKey: kbKeys.all });
      router.push(`/kb/${doc.space.id}`);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <article className="space-y-4">
      <header className="space-y-1">
        <p className="font-mono text-xs text-muted-foreground">
          <span>{doc.space.name}</span> · <span>{kbPath(doc)}</span>
        </p>
        <h1 className="text-lg font-bold text-cyan-ink glow-cyan">{doc.title}</h1>
        <p className="text-xs text-muted-foreground">
          <span className="font-mono">rev {doc.latest_revision}</span> · updated by {revisionAuthor(doc.updated_by)} on{" "}
          {new Date(doc.updated_at).toLocaleString()}
        </p>
        <div className="flex flex-wrap gap-2 pt-1">
          {doc.can_write && (
            <>
              <Button onClick={onEdit}>Edit</Button>
              <Button variant="ghost" onClick={() => setMoving((m) => !m)}>
                Move
              </Button>
            </>
          )}
          {doc.can_delete && (
            <Button variant="danger" onClick={remove}>
              Delete
            </Button>
          )}
        </div>
        {error && (
          <p role="alert" className="text-sm text-pink">
            {error}
          </p>
        )}
      </header>
      {moving && <MoveForm doc={doc} onDone={() => setMoving(false)} />}
      <div className="card kb-prose p-4">
        {doc.body_md.trim() ? <KbMarkdown>{doc.body_md}</KbMarkdown> : <p className="text-sm text-muted-foreground">This document is empty.</p>}
      </div>
      <div className="card p-4">
        <Backlinks docId={doc.id} />
      </div>
    </article>
  );
}

function MoveForm({ doc, onDone }: { doc: KbDocument; onDone: () => void }) {
  const client = useQueryClient();
  const spaces = useKbSpaces();
  const [target, setTarget] = useState(doc.space.id);
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      className="card flex flex-wrap items-end gap-2 p-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        try {
          const moved = await api<KbDocument>(`/api/kb/documents/${doc.id}/move`, {
            method: "POST",
            json: { space_id: target, folder_id: null },
          });
          client.setQueryData(kbKeys.doc(doc.id), moved);
          await client.invalidateQueries({ queryKey: kbKeys.all });
          onDone();
        } catch (err) {
          setError(errorMessage(err));
        }
      }}
    >
      <div className="min-w-[14rem] flex-1">
        <Select label="Move to space (top level)" value={target} onChange={(e) => setTarget(e.target.value)}>
          {(spaces.data ?? [])
            .filter((s) => s.can_write)
            .map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
        </Select>
      </div>
      <Button type="submit">Move</Button>
      <Button variant="ghost" onClick={onDone}>
        Cancel
      </Button>
      {error && (
        <p role="alert" className="w-full text-sm text-pink">
          {error}
        </p>
      )}
      <p className="w-full text-xs text-muted-foreground">Only people who can read the target space will see the document there.</p>
    </form>
  );
}
