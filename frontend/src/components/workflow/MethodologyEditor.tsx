"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Markdown } from "@/components/ui/Markdown";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useUsers } from "@/lib/project";
import type { MethodologyItem, MethodologyVersion, MethodologyVersionInfo } from "@/lib/types";

export const MAX_CHARS = 50_000;

const STAGE_CARDS: { id: string; label: string; keys: string[] }[] = [
  { id: "brainstorm", label: "Brainstorm", keys: ["brainstorm"] },
  { id: "design", label: "Design", keys: ["design_revision"] },
  { id: "plan", label: "Plan", keys: ["plan"] },
  { id: "build", label: "Build", keys: ["build_implement", "build_step_review", "build_step_fix"] },
  { id: "review", label: "Review", keys: ["review_final", "review_fix"] },
  { id: "done", label: "Done", keys: ["finish"] },
];

const mqk = {
  list: () => ["methodology"] as const,
  versions: (key: string) => ["methodology", key, "versions"] as const,
  version: (key: string, v: number) => ["methodology", key, "version", v] as const,
};

const DISCARD = "Discard your unsaved changes?";

const when = (iso: string) => new Date(iso).toLocaleString();

function History({
  itemKey,
  names,
  onRestore,
}: {
  itemKey: string;
  names: Map<string, string>;
  onRestore: (body: string) => void;
}) {
  const [selected, setSelected] = useState<number | null>(null);
  const versions = useQuery({
    queryKey: mqk.versions(itemKey),
    queryFn: () => api<MethodologyVersionInfo[]>(`/api/methodology/${itemKey}/versions`),
  });
  const detail = useQuery({
    queryKey: mqk.version(itemKey, selected ?? 0),
    queryFn: () => api<MethodologyVersion>(`/api/methodology/${itemKey}/versions/${selected}`),
    enabled: selected !== null,
  });
  return (
    <div className="mt-3 space-y-3 border-t border-line pt-3">
      {versions.error && <p className="text-sm text-pink">{errorMessage(versions.error)}</p>}
      <ul className="space-y-1">
        {versions.data?.map((v) => (
          <li key={v.version}>
            <button
              type="button"
              aria-pressed={selected === v.version}
              onClick={() => setSelected(v.version)}
              className={`text-left text-sm ${selected === v.version ? "text-cyan-ink" : "text-muted hover:text-fg"}`}
            >
              v{v.version} · {when(v.created_at)} · {v.created_by ? (names.get(v.created_by) ?? "Unknown user") : "System"}
            </button>
          </li>
        ))}
      </ul>
      {detail.error && <p className="text-sm text-pink">{errorMessage(detail.error)}</p>}
      {detail.data && selected !== null && (
        <div className="space-y-2 rounded border border-line p-3">
          <p className="text-xs tracking-wider text-muted uppercase">Version {detail.data.version} (read-only)</p>
          <Markdown>{detail.data.body_md}</Markdown>
          <Button variant="ghost" type="button" onClick={() => onRestore(detail.data.body_md)}>
            Restore as new version
          </Button>
        </div>
      )}
    </div>
  );
}

function KeyEditor({ item, names }: { item: MethodologyItem; names: Map<string, string> }) {
  const client = useQueryClient();
  // null = no edits yet: the textarea follows the saved text. `base` is the version the draft started from (its
  // first edit, or a restore): a save sends it, so a version saved meanwhile is a conflict, even after a refetch.
  const [draft, setDraft] = useState<{ text: string; base: number } | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string; conflict?: boolean } | null>(null);

  const text = draft?.text ?? item.body_md;
  const dirty = draft !== null && draft.text !== item.body_md;
  const length = Array.from(text).length;
  const tooLong = length > MAX_CHARS;

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
    document.addEventListener("click", guardLinks, true);
    return () => document.removeEventListener("click", guardLinks, true);
  }, [dirty]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const refresh = () => client.invalidateQueries({ queryKey: mqk.list() });

  async function save() {
    const sent = text;
    setSaving(true);
    setMsg(null);
    try {
      const saved = await api<{ version: number }>(`/api/methodology/${item.key}`, {
        method: "PUT",
        json: { body_md: sent, base_version: draft?.base ?? item.version },
      });
      await refresh();
      await client.invalidateQueries({ queryKey: mqk.versions(item.key) });
      // text typed while saving stays a draft, now on top of the version just saved
      setDraft((d) => (d === null || d.text === sent ? null : { ...d, base: saved.version }));
      setMsg({ ok: true, text: `Saved as v${saved.version}` });
    } catch (err) {
      setMsg({ ok: false, text: errorMessage(err), conflict: err instanceof ApiError && err.status === 409 });
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-label={item.key} className="rounded border border-line p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-mono text-sm">{item.key}</h3>
        <p className="text-xs text-muted">
          <span className="text-cyan-ink">v{item.version}</span> · updated {when(item.updated_at)}
          {item.updated_by ? ` by ${names.get(item.updated_by) ?? "an unknown user"}` : ""}
        </p>
      </div>
      <textarea
        aria-label={`Instructions for ${item.key}`}
        className="mt-2 min-h-48 w-full rounded border border-line bg-surface-2 px-2 py-1 font-mono text-sm"
        value={text}
        onChange={(e) => {
          const value = e.target.value;
          setDraft((d) => ({ text: value, base: d?.base ?? item.version }));
        }}
      />
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <Button type="button" disabled={!dirty || length === 0 || tooLong || saving} onClick={save}>
          Save
        </Button>
        <Button type="button" variant="ghost" onClick={() => setShowHistory((s) => !s)} aria-expanded={showHistory}>
          History
        </Button>
        <span className={`ml-auto text-xs ${tooLong ? "text-pink" : "text-muted"}`}>
          {length.toLocaleString("en-US")} / {MAX_CHARS.toLocaleString("en-US")}
        </span>
      </div>
      {msg && (
        <div role="status" className={`mt-2 flex flex-wrap items-center gap-2 text-sm ${msg.ok ? "text-green-ink" : "text-pink"}`}>
          <span>{msg.text}</span>
          {msg.conflict && (
            <Button
              type="button"
              variant="ghost"
              onClick={async () => {
                if (dirty && !window.confirm(DISCARD)) return;
                await refresh();
                setDraft(null);
                setMsg(null);
              }}
            >
              Load latest
            </Button>
          )}
        </div>
      )}
      {showHistory && (
        <History
          itemKey={item.key}
          names={names}
          onRestore={(body) => {
            if (dirty && !window.confirm(DISCARD)) return;
            setDraft({ text: body, base: item.version });
            setMsg(null);
          }}
        />
      )}
    </section>
  );
}

export function MethodologyEditor() {
  const list = useQuery({ queryKey: mqk.list(), queryFn: () => api<MethodologyItem[]>("/api/methodology") });
  const users = useUsers();
  const names = new Map(users.data?.map((u) => [u.id, u.name]));
  const byKey = new Map(list.data?.map((m) => [m.key, m]));

  if (list.error) return <p className="text-sm text-pink">{errorMessage(list.error)}</p>;
  if (!list.data) return null;
  return (
    <div className="space-y-4">
      {STAGE_CARDS.map((stage) => (
        <div key={stage.id} className="card space-y-3 p-4">
          <h2 className="text-sm font-bold text-cyan-ink">{stage.label}</h2>
          {stage.keys.map((k) => {
            const item = byKey.get(k);
            return item ? <KeyEditor key={k} item={item} names={names} /> : null;
          })}
        </div>
      ))}
      <p className="text-xs text-muted">
        Adapted from{" "}
        <a href="https://github.com/obra/superpowers" target="_blank" rel="noopener noreferrer">
          obra/superpowers
        </a>{" "}
        (MIT)
      </p>
    </div>
  );
}
