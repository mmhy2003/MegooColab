"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Folder, FolderPlus, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { kbKeys, type KbFolder, type KbTreeDoc } from "@/lib/kb";

type Props = {
  spaceId: string;
  folders: KbFolder[];
  documents: KbTreeDoc[];
  selected: string | null;
  onSelect: (folderId: string | null) => void;
  canWrite: boolean;
};

/** A space's folders as a tree; selecting one shows its documents. Writers create, rename and delete folders. */
export function FolderTree({ spaceId, folders, documents, selected, onSelect, canWrite }: Props) {
  const client = useQueryClient();
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const children = (parent: string | null) =>
    folders.filter((f) => f.parent_id === parent).sort((a, b) => a.name.localeCompare(b.name));
  const refresh = () => client.invalidateQueries({ queryKey: kbKeys.tree(spaceId) });

  function isEmpty(id: string): boolean {
    return !folders.some((f) => f.parent_id === id) && !documents.some((d) => d.folder_id === id);
  }

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function remove(f: KbFolder) {
    const empty = isEmpty(f.id);
    const question = empty
      ? `Delete folder ${f.name}?`
      : `Delete folder ${f.name} and its subfolders? The documents inside move up to the parent folder; none are deleted.`;
    if (!confirm(question)) return;
    await run(async () => {
      await api(`/api/kb/folders/${f.id}${empty ? "" : "?recursive=true"}`, { method: "DELETE" });
      if (selected === f.id) onSelect(f.parent_id ?? null);
    });
  }

  async function rename(f: KbFolder) {
    const next = prompt("New folder name", f.name)?.trim();
    if (!next || next === f.name) return;
    await run(() => api(`/api/kb/folders/${f.id}`, { method: "PATCH", json: { name: next } }));
  }

  function renderFolder(f: KbFolder) {
    const kids = children(f.id);
    const open = !collapsed.has(f.id);
    return (
      <li key={f.id} role="treeitem" aria-selected={selected === f.id} aria-expanded={kids.length ? open : undefined} aria-label={f.name}>
        <div className={`group flex items-center gap-1 rounded px-1 ${selected === f.id ? "bg-surface-2 text-cyan-ink" : ""}`}>
          {kids.length ? (
            <button
              type="button"
              className="icon-btn"
              aria-label={`${open ? "Collapse" : "Expand"} ${f.name}`}
              onClick={() => {
                const next = new Set(collapsed);
                if (open) next.add(f.id);
                else next.delete(f.id);
                setCollapsed(next);
              }}
            >
              {open ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
            </button>
          ) : (
            <span className="inline-block w-[22px]" aria-hidden />
          )}
          <button type="button" className="flex min-w-0 flex-1 items-center gap-1 py-1 text-left text-sm" onClick={() => onSelect(f.id)}>
            <Folder size={14} aria-hidden className="shrink-0 text-muted-foreground" />
            <span className="min-w-0 truncate">{f.name}</span>
          </button>
          {canWrite && (
            <span className="flex opacity-70 group-hover:opacity-100">
              <button type="button" className="icon-btn" aria-label={`Rename folder ${f.name}`} onClick={() => rename(f)}>
                <Pencil size={12} aria-hidden />
              </button>
              <button type="button" className="icon-btn" aria-label={`Delete folder ${f.name}`} onClick={() => remove(f)}>
                <Trash2 size={12} aria-hidden />
              </button>
            </span>
          )}
        </div>
        {kids.length > 0 && open && (
          <ul role="group" className="ml-4">
            {kids.map(renderFolder)}
          </ul>
        )}
      </li>
    );
  }

  return (
    <div className="space-y-2">
      <ul role="tree" aria-label="Folders" className="space-y-0.5">
        <li role="treeitem" aria-selected={selected === null} aria-label="All documents">
          <button
            type="button"
            className={`w-full rounded px-2 py-1 text-left text-sm ${selected === null ? "bg-surface-2 text-cyan-ink" : ""}`}
            onClick={() => onSelect(null)}
          >
            All documents
          </button>
        </li>
        {children(null).map(renderFolder)}
      </ul>
      {error && (
        <p role="alert" className="text-sm text-pink">
          {error}
        </p>
      )}
      {canWrite &&
        (creating ? (
          <form
            className="space-y-2"
            onSubmit={async (e) => {
              e.preventDefault();
              await run(async () => {
                await api(`/api/kb/spaces/${spaceId}/folders`, {
                  method: "POST",
                  json: { name: name.trim(), parent_id: selected },
                });
                setCreating(false);
                setName("");
              });
            }}
          >
            <Input label="Folder name" required maxLength={100} pattern="[^/\\\\]+" value={name} onChange={(e) => setName(e.target.value)} />
            <div className="flex gap-2">
              <Button type="submit">Create</Button>
              <Button variant="ghost" onClick={() => setCreating(false)}>
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <Button variant="ghost" onClick={() => setCreating(true)}>
            <FolderPlus size={14} aria-hidden /> New folder
          </Button>
        ))}
    </div>
  );
}
