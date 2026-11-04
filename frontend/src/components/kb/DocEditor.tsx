"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { BODY_MAX, MarkdownField } from "@/components/kb/MarkdownField";
import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";
import { ApiError, api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { kbKeys, type KbDocument } from "@/lib/kb";
import { DISCARD, useUnsavedGuard } from "@/lib/unsaved";

/** Edits a document. Saves carry the revision the edit started from, so a newer save is never overwritten. */
export function DocEditor({
  doc,
  onSaved,
  onCancel,
}: {
  doc: KbDocument;
  onSaved: (doc: KbDocument) => void;
  onCancel: () => void;
}) {
  const client = useQueryClient();
  const { ask, dialog } = useConfirm();
  const [base, setBase] = useState(doc.latest_revision);
  const [original, setOriginal] = useState({ title: doc.title, body: doc.body_md });
  const [title, setTitle] = useState(doc.title);
  const [body, setBody] = useState(doc.body_md);
  const [summary, setSummary] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<{ text: string; conflict: boolean } | null>(null);
  const dirty = title !== original.title || body !== original.body;
  const tooLong = body.length > BODY_MAX;

  useUnsavedGuard(dirty, ask);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const saved = await api<KbDocument>(`/api/kb/documents/${doc.id}`, {
        method: "PUT",
        json: { base_revision: base, title: title.trim(), body_md: body, summary: summary.trim() || null },
      });
      client.setQueryData(kbKeys.doc(doc.id), saved);
      await client.invalidateQueries({ queryKey: kbKeys.all });
      onSaved(saved);
    } catch (err) {
      const conflict = err instanceof ApiError && err.detail === "kb_conflict";
      setError({
        text: conflict ? "Someone saved a newer version. Your text is kept here." : errorMessage(err),
        conflict,
      });
    } finally {
      setSaving(false);
    }
  }

  async function loadLatest() {
    const replace = await ask({
      tone: "warn",
      title: "Load the latest version?",
      text: "Your unsaved changes here are replaced by it.",
      ok: "Load latest",
      cancel: "Keep mine",
    });
    if (!replace) return;
    try {
      const latest = await api<KbDocument>(`/api/kb/documents/${doc.id}`);
      client.setQueryData(kbKeys.doc(doc.id), latest);
      setBase(latest.latest_revision);
      setOriginal({ title: latest.title, body: latest.body_md });
      setTitle(latest.title);
      setBody(latest.body_md);
      setError(null);
    } catch (err) {
      setError({ text: errorMessage(err), conflict: true });
    }
  }

  return (
    <>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <Input label="Title" required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
        <MarkdownField id="kb-body" value={body} onChange={setBody} />
        <Input
          label="Summary of change (optional)"
          maxLength={200}
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
        />
        {error && (
          <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-pink">
            <span>{error.text}</span>
            {error.conflict && (
              <Button variant="ghost" onClick={loadLatest}>
                Load latest
              </Button>
            )}
          </div>
        )}
        <div className="flex gap-2">
          <Button type="submit" disabled={saving || tooLong || !title.trim()}>
            Save
          </Button>
          <Button
            variant="ghost"
            onClick={async () => {
              if (!dirty || (await ask(DISCARD))) onCancel();
            }}
          >
            Cancel
          </Button>
        </div>
      </form>
      {dialog}
    </>
  );
}
