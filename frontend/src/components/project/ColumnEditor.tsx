"use client";

import { ChevronLeft, ChevronRight, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Column, ColumnCategory } from "@/lib/types";
import { Hint } from "@/components/ui/Hint";
import { useConfirm } from "@/components/ui/ConfirmDialog";

export const CATEGORY_LABEL: Record<ColumnCategory, string> = {
  before: "Before work",
  working: "Working",
  review: "Review",
  done: "Done",
};
const CATEGORIES = Object.keys(CATEGORY_LABEL) as ColumnCategory[];

export function ColumnEditor({
  projectKey,
  columns,
  onChanged,
}: {
  projectKey: string;
  columns: Column[];
  onChanged: () => void;
}) {
  const { ask, dialog } = useConfirm();
  const base = `/api/projects/${projectKey}/columns`;
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Column | null>(null);
  const [moveTo, setMoveTo] = useState("");
  const [newName, setNewName] = useState("");
  const [newCategory, setNewCategory] = useState<ColumnCategory>("working");

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      onChanged();
      return true;
    } catch (err) {
      setError(errorMessage(err));
      return false;
    }
  }

  function move(index: number, delta: number) {
    const ids = columns.map((c) => c.id);
    const [moved] = ids.splice(index, 1);
    ids.splice(index + delta, 0, moved);
    void run(() => api(`${base}/order`, { method: "PUT", json: { column_ids: ids } }));
  }

  async function startDelete(col: Column) {
    if (col.task_count > 0) {
      setMoveTo(columns.find((c) => c.id !== col.id)?.id ?? "");
      setDeleting(col);
    } else if (await ask({ tone: "danger", title: `Delete column ${col.name}?`, text: "It has no tasks.", ok: "Delete" })) {
      void run(() => api(`${base}/${col.id}`, { method: "DELETE" }));
    }
  }

  return (
    <>
      <div className="space-y-4">
        {error && <p role="alert" className="text-sm text-pink">{error}</p>}
        <ol className="flex gap-3 overflow-x-auto pb-2">
          {columns.map((col, i) => (
            <li key={col.id} className="card w-52 shrink-0 space-y-2 p-3">
              <input
                aria-label={`Name of ${col.name}`}
                defaultValue={col.name}
                className="w-full rounded border border-line bg-surface-2 px-2 py-1 text-sm"
                onBlur={(e) => {
                  const name = e.target.value.trim();
                  if (name && name !== col.name) void run(() => api(`${base}/${col.id}`, { method: "PATCH", json: { name } }));
                }}
              />
              <select
                aria-label={`Category of ${col.name}`}
                value={col.category}
                className="w-full rounded border border-line bg-surface-2 px-2 py-1 text-xs"
                onChange={(e) => void run(() => api(`${base}/${col.id}`, { method: "PATCH", json: { category: e.target.value } }))}
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>
                ))}
              </select>
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>{col.task_count} tasks</span>
                <span className="flex">
                  <Hint label={`Move ${col.name} left`}>
                    <button type="button" className="icon-btn" aria-label={`Move ${col.name} left`} disabled={i === 0} onClick={() => move(i, -1)}>
                      <ChevronLeft size={14} aria-hidden />
                    </button>
                  </Hint>
                  <Hint label={`Move ${col.name} right`}>
                    <button type="button" className="icon-btn" aria-label={`Move ${col.name} right`} disabled={i === columns.length - 1} onClick={() => move(i, 1)}>
                      <ChevronRight size={14} aria-hidden />
                    </button>
                  </Hint>
                  <Hint label={`Delete ${col.name}`}>
                    <button type="button" className="icon-btn hover:text-pink" aria-label={`Delete ${col.name}`} onClick={() => startDelete(col)}>
                      <Trash2 size={14} aria-hidden />
                    </button>
                  </Hint>
                </span>
              </div>
            </li>
          ))}
        </ol>
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            if (await run(() => api(base, { method: "POST", json: { name: newName, category: newCategory } }))) setNewName("");
          }}
        >
          <input
            aria-label="New column name"
            placeholder="New column name"
            required
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            className="rounded border border-line bg-surface-2 px-2 py-1.5 text-sm"
          />
          <select
            aria-label="New column category"
            value={newCategory}
            onChange={(e) => setNewCategory(e.target.value as ColumnCategory)}
            className="rounded border border-line bg-surface-2 px-2 py-1.5 text-sm"
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>
            ))}
          </select>
          <Button type="submit" variant="ghost">Add column</Button>
        </form>
        {deleting && (
          <Dialog open title={`Delete ${deleting.name}`} onClose={() => setDeleting(null)}>
            <div className="space-y-3">
              <Select label={`Move its ${deleting.task_count} tasks to`} value={moveTo} onChange={(e) => setMoveTo(e.target.value)}>
                {columns
                  .filter((c) => c.id !== deleting.id)
                  .map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
              </Select>
              <Button
                variant="danger"
                onClick={async () => {
                  const ok = await run(() => api(`${base}/${deleting.id}?move_to=${moveTo}`, { method: "DELETE" }));
                  if (ok) setDeleting(null);
                }}
              >
                Delete column
              </Button>
            </div>
          </Dialog>
        )}
      </div>
      {dialog}
    </>
  );
}
