"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Pin } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ReasoningChain } from "@/components/memory/ReasoningChain";
import { Button } from "@/components/ui/Button";
import { Markdown } from "@/components/ui/Markdown";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { kindLabel, memKeys, useMemConclusion, type MemConclusion } from "@/lib/memory";

const TEXT_MAX = 500;

function Why({ id }: { id: string }) {
  const detail = useMemConclusion(id);
  if (detail.error) return <p className="text-xs text-pink">{errorMessage(detail.error)}</p>;
  if (!detail.data) return <p className="text-xs text-muted-foreground">Loading…</p>;
  return <ReasoningChain nodes={detail.data.premises} />;
}

/** One conclusion: its text, kind, scope and source; correct, delete and pin for those allowed (MEM-8). */
export function ConclusionItem({ conclusion: c }: { conclusion: MemConclusion }) {
  const client = useQueryClient();
  const [why, setWhy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(c.text);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await client.invalidateQueries({ queryKey: memKeys.all });
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <li className="space-y-2 py-3">
      <div className="kb-prose">
        <Markdown>{c.text}</Markdown>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="rounded border border-line px-1.5 font-mono">{kindLabel(c)}</span>
        {c.pinned && (
          <span className="inline-flex items-center gap-1 text-cyan-ink">
            <Pin size={12} aria-hidden /> Pinned
          </span>
        )}
        {c.status !== "active" && <span className="text-pink">{c.status}</span>}
        <span className="rounded border border-line px-1.5">{c.scope.name}</span>
        {c.source &&
          (c.source.link ? (
            <Link href={c.source.link}>{c.source.label}</Link>
          ) : (
            <span>(source deleted)</span>
          ))}
        <span>{new Date(c.created_at).toLocaleDateString()}</span>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="ghost" onClick={() => setWhy((w) => !w)} aria-expanded={why}>
          Why?
        </Button>
        {c.can_edit && c.status === "active" && (
          <>
            <Button variant="ghost" onClick={() => setEditing((e) => !e)}>
              Correct
            </Button>
            <Button
              variant="ghost"
              onClick={() =>
                run(() => api(`/api/memory/conclusions/${c.id}/pin`, { method: "POST", json: { pinned: !c.pinned } }))
              }
            >
              {c.pinned ? "Unpin" : "Pin"}
            </Button>
          </>
        )}
        {c.can_edit && c.status !== "deleted" && (
          <Button
            variant="danger"
            onClick={() => {
              if (!confirm("Delete this conclusion? It will not be learned again from its source.")) return;
              void run(() => api(`/api/memory/conclusions/${c.id}`, { method: "DELETE" }));
            }}
          >
            Delete
          </Button>
        )}
      </div>
      {editing && (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            void run(async () => {
              await api(`/api/memory/conclusions/${c.id}/correct`, { method: "POST", json: { text: text.trim() } });
              setEditing(false);
            });
          }}
        >
          <label htmlFor={`correct-${c.id}`} className="text-xs tracking-wider text-muted-foreground uppercase">
            Corrected text
          </label>
          <textarea
            id={`correct-${c.id}`}
            required
            maxLength={TEXT_MAX}
            rows={2}
            className="w-full rounded border border-line bg-surface-2 px-3 py-2 text-sm text-fg focus:border-cyan focus:outline-none"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="flex gap-2">
            <Button type="submit">Save correction</Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </form>
      )}
      {error && (
        <p role="alert" className="text-sm text-pink">
          {error}
        </p>
      )}
      {why && <Why id={c.id} />}
    </li>
  );
}
