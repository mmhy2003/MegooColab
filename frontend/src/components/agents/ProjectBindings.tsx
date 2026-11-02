"use client";

import { Pencil, Plus, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import { isAbsolutePath } from "@/lib/agents";
import { errorMessage } from "@/lib/errors";
import type { Agent, Project } from "@/lib/types";

type Binding = Agent["bindings"][number];

const SHOWN = 10;
const BAD_PATH = "Enter the full path to the repository, such as C:\\code\\payments or /home/me/code/payments.";

/** The projects an agent works on and where each repository lives on its machine: one line each, searchable,
 * shortened past ten. Every add, folder change and removal is saved at once, one at a time. */
export function ProjectBindings({
  agent,
  projects,
  onSaved,
}: {
  agent: Agent;
  projects: Project[];
  onSaved: () => Promise<unknown>;
}) {
  const { ask, dialog } = useConfirm();
  const [query, setQuery] = useState("");
  const [all, setAll] = useState(false);
  const [adding, setAdding] = useState<{ project: string; folder: string } | null>(null);
  const [editing, setEditing] = useState<{ key: string; folder: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // what the last save stored, until the agent's refetched bindings replace it: the next change builds on it even
  // when that refetch fails
  const [last, setLast] = useState<{ from: Binding[]; bindings: Binding[] } | null>(null);
  const bindings = last && last.from === agent.bindings ? last.bindings : agent.bindings;

  const nameOf = new Map(projects.map((p) => [p.key, p.name]));
  const bound = new Set(bindings.map((b) => b.project_key));
  const label = (b: Binding) => [b.project_key, nameOf.get(b.project_key)].filter(Boolean).join(" ");
  const sorted = [...bindings].sort((a, b) => a.project_key.localeCompare(b.project_key));
  const q = query.trim().toLowerCase();
  const matches = q
    ? sorted.filter((b) => `${label(b)}\n${b.local_path ?? ""}`.toLowerCase().includes(q))
    : sorted;
  const lines = q || all ? matches : matches.slice(0, SHOWN);

  /** Saves the agent's saved bindings with one change; false when it did not save. */
  const save = async (next: { project_ref: string; local_path: string }[]) => {
    setSaving(true);
    setError(null);
    try {
      await api(`/api/agents/${agent.id}/bindings`, { method: "PUT", json: { bindings: next } });
      const id = new Map(bindings.map((b) => [b.project_key, b.project_id]));
      setLast({
        from: agent.bindings,
        bindings: next.map((n) => ({ project_id: id.get(n.project_ref) ?? n.project_ref, project_key: n.project_ref, local_path: n.local_path })),
      });
      await onSaved();
      return true;
    } catch (err) {
      setError(errorMessage(err));
      return false;
    } finally {
      setSaving(false);
    }
  };
  const saved = () => bindings.map((b) => ({ project_ref: b.project_key, local_path: b.local_path ?? "" }));

  const addRow = async () => {
    if (!adding) return;
    const folder = adding.folder.trim();
    if (!adding.project) return setError("Choose a project.");
    if (!isAbsolutePath(folder)) return setError(BAD_PATH);
    if (await save([...saved(), { project_ref: adding.project, local_path: folder }])) {
      // the new line shows, wherever it sorts and whatever was searched
      setQuery("");
      setAll(true);
      setAdding(null);
    }
  };
  const saveEdit = async () => {
    if (!editing) return;
    const folder = editing.folder.trim();
    if (!isAbsolutePath(folder)) return setError(BAD_PATH);
    const next = saved().map((b) => (b.project_ref === editing.key ? { ...b, local_path: folder } : b));
    if (await save(next)) setEditing(null);
  };
  const remove = async (b: Binding) => {
    const ok = await ask({ tone: "danger", title: `Remove ${b.project_key} from ${agent.name}?`, text: "The agent stops working on it.", ok: "Remove" });
    if (ok) await save(saved().filter((s) => s.project_ref !== b.project_key));
  };
  const alert = error && <p role="alert" className="text-sm text-pink">{error}</p>;

  return (
    <div className="space-y-2">
      {dialog}
      <h3 className="text-xs tracking-wider text-muted-foreground uppercase">Projects ({bindings.length})</h3>
      <div className="flex items-end gap-2">
        {bindings.length > 0 && (
          <div className="min-w-0 flex-1">
            <Input label="Search projects" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Key, name or folder" />
          </div>
        )}
        <Button
          variant="ghost"
          disabled={saving || adding !== null}
          onClick={() => {
            setEditing(null);
            setError(null);
            setAdding({ project: "", folder: "" });
          }}
        >
          <Plus size={14} aria-hidden />
          Add project
        </Button>
      </div>
      {adding && (
        <div className="space-y-2 rounded border border-dashed border-line p-2">
          <div className="grid gap-2 md:grid-cols-[minmax(0,12rem)_minmax(0,1fr)_auto] md:items-end">
            <Select label="Project" value={adding.project} onChange={(e) => setAdding({ ...adding, project: e.target.value })}>
              <option value="">Choose a project</option>
              {projects.filter((p) => !bound.has(p.key)).map((p) => (
                <option key={p.id} value={p.key}>{p.key} {p.name}</option>
              ))}
            </Select>
            <Input
              label="Folder"
              placeholder="C:\code\payments or /home/me/code/payments"
              value={adding.folder}
              onChange={(e) => setAdding({ ...adding, folder: e.target.value })}
            />
            <div className="flex gap-2">
              <Button disabled={saving} onClick={addRow}>Add</Button>
              <Button variant="ghost" disabled={saving} onClick={() => { setAdding(null); setError(null); }}>Cancel</Button>
            </div>
          </div>
          {alert}
        </div>
      )}
      {bindings.length === 0 && !adding && <p className="text-sm text-muted-foreground">Not working on any project yet.</p>}
      {q && matches.length === 0 && <p className="text-sm text-muted-foreground">No project matches.</p>}
      <ul className="divide-y divide-line rounded border border-line empty:hidden">
        {lines.map((b) =>
          editing?.key === b.project_key ? (
            <li key={b.project_key} className="space-y-2 p-2">
              <div className="grid gap-2 md:grid-cols-[minmax(0,12rem)_minmax(0,1fr)_auto] md:items-end">
                <span className="truncate pb-2 text-sm font-bold">{label(b)}</span>
                <Input label="Folder" value={editing.folder} onChange={(e) => setEditing({ ...editing, folder: e.target.value })} />
                <div className="flex gap-2">
                  <Button disabled={saving} onClick={saveEdit}>Save</Button>
                  <Button variant="ghost" disabled={saving} onClick={() => { setEditing(null); setError(null); }}>Cancel</Button>
                </div>
              </div>
              {alert}
            </li>
          ) : (
            <li
              key={b.project_key}
              className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 px-2 py-1.5 md:grid-cols-[minmax(0,12rem)_minmax(0,1fr)_auto]"
            >
              <span className="truncate text-sm font-bold">{label(b)}</span>
              <span title={b.local_path ?? ""} className="truncate font-mono text-xs text-muted-foreground max-md:col-start-1 max-md:row-start-2">
                {b.local_path}
              </span>
              <span className="flex gap-1 max-md:row-span-2 max-md:col-start-2 max-md:row-start-1">
                <button
                  type="button"
                  className="icon-btn"
                  aria-label={`Edit folder of ${b.project_key}`}
                  disabled={saving}
                  onClick={() => {
                    setAdding(null);
                    setError(null);
                    setEditing({ key: b.project_key, folder: b.local_path ?? "" });
                  }}
                >
                  <Pencil size={14} aria-hidden />
                </button>
                <button type="button" className="icon-btn" aria-label={`Remove ${b.project_key}`} disabled={saving} onClick={() => void remove(b)}>
                  <X size={14} aria-hidden />
                </button>
              </span>
            </li>
          ),
        )}
      </ul>
      {!adding && !editing && alert}
      {!q && !all && matches.length > SHOWN && (
        <Button variant="ghost" onClick={() => setAll(true)}>{`Show ${matches.length - SHOWN} more`}</Button>
      )}
    </div>
  );
}
