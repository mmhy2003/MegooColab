"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Markdown } from "@/components/ui/Markdown";

export function Description({
  value,
  disabled,
  onSave,
}: {
  value: string;
  disabled: boolean;
  onSave: (md: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [preview, setPreview] = useState(false);

  if (!editing) {
    return (
      <div>
        {value ? <Markdown>{value}</Markdown> : <p className="text-sm text-muted-foreground">No description.</p>}
        {!disabled && (
          <button type="button" className="mt-1 text-xs text-cyan-ink" onClick={() => { setDraft(value); setEditing(true); }}>
            Edit description
          </button>
        )}
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <div className="flex gap-2 text-xs">
        <button type="button" aria-pressed={!preview} className={!preview ? "text-cyan-ink" : "text-muted-foreground"} onClick={() => setPreview(false)}>Write</button>
        <button type="button" aria-pressed={preview} className={preview ? "text-cyan-ink" : "text-muted-foreground"} onClick={() => setPreview(true)}>Preview</button>
      </div>
      {preview ? (
        <div className="min-h-24 rounded border border-line p-2"><Markdown>{draft || "_Nothing to preview._"}</Markdown></div>
      ) : (
        <textarea
          aria-label="Description (Markdown)"
          className="min-h-40 w-full rounded border border-line bg-surface-2 p-2 text-sm"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
      )}
      <div className="flex gap-2">
        <Button onClick={async () => { await onSave(draft); setEditing(false); }}>Save</Button>
        <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
      </div>
    </div>
  );
}
