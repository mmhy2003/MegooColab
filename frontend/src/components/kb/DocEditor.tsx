"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { KbMarkdown } from "@/components/kb/KbMarkdown";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ApiError, api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { kbKeys, type KbDocument } from "@/lib/kb";

const BODY_MAX = 500_000;
const DISCARD = "Discard your unsaved changes?";

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
  const [base, setBase] = useState(doc.latest_revision);
  const [original, setOriginal] = useState({ title: doc.title, body: doc.body_md });
  const [title, setTitle] = useState(doc.title);
  const [body, setBody] = useState(doc.body_md);
  const [summary, setSummary] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<{ text: string; conflict: boolean } | null>(null);
  const dirty = title !== original.title || body !== original.body;
  const tooLong = body.length > BODY_MAX;

  useEffect(() => {
    if (!dirty) return;
    // in-app navigation: ask before following any same-origin link
    const guardLinks = (e: MouseEvent) => {
      const a = e.target instanceof Element ? e.target.closest("a[href]") : null;
      if (!a || (a as HTMLAnchorElement).target === "_blank") return;
      if ((a as HTMLAnchorElement).origin !== window.location.origin) return;
      if (!window.confirm(DISCARD)) {
        e.preventDefault();
        e.stopPropagation();
      }
    };
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    document.addEventListener("click", guardLinks, true);
    window.addEventListener("beforeunload", warn);
    return () => {
      document.removeEventListener("click", guardLinks, true);
      window.removeEventListener("beforeunload", warn);
    };
  }, [dirty]);

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
    if (!window.confirm("Load the latest version? Your unsaved changes here will be replaced.")) return;
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
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <Input label="Title" required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-2">
        <div className="flex flex-col gap-1">
          <label htmlFor="kb-body" className="text-xs tracking-wider text-muted uppercase">
            Body
          </label>
          <textarea
            id="kb-body"
            className="min-h-[24rem] w-full rounded border border-line bg-surface-2 px-3 py-2 font-mono text-sm text-fg focus:border-cyan focus:outline-none"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            aria-invalid={tooLong || undefined}
          />
          <p className={`text-xs ${tooLong ? "text-pink" : "text-muted"}`}>
            {body.length.toLocaleString("en-US")} / {BODY_MAX.toLocaleString("en-US")} characters. Link with [[PAY-12]] or
            [[doc:&lt;id&gt;|Title]].
          </p>
        </div>
        <section aria-label="Preview" className="min-w-0 rounded border border-line p-3">
          <p className="mb-2 text-xs tracking-wider text-muted uppercase">Preview</p>
          <div className="kb-prose">
            <KbMarkdown>{body}</KbMarkdown>
          </div>
        </section>
      </div>
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
          onClick={() => {
            if (!dirty || window.confirm(DISCARD)) onCancel();
          }}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}
