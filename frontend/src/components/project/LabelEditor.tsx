"use client";

import { Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Label } from "@/lib/types";

export function LabelChip({ label }: { label: Label }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-sm border px-1.5 text-[11px]" style={{ borderColor: label.color, color: "var(--fg)" }}>
      <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: label.color }} />
      {label.name}
    </span>
  );
}

export function LabelEditor({ projectKey, labels, onChanged }: { projectKey: string; labels: Label[]; onChanged: () => void }) {
  const base = `/api/projects/${projectKey}/labels`;
  const [name, setName] = useState("");
  const [color, setColor] = useState("#05D9E8");
  const [error, setError] = useState<string | null>(null);

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

  return (
    <div className="space-y-3">
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      <ul className="flex flex-wrap gap-2">
        {labels.map((l) => (
          <li key={l.id} className="flex items-center gap-1">
            <LabelChip label={l} />
            <button type="button" className="icon-btn h-6 w-6 hover:text-pink" aria-label={`Delete label ${l.name}`} onClick={() => run(() => api(`${base}/${l.id}`, { method: "DELETE" }))}>
              <Trash2 size={12} aria-hidden />
            </button>
          </li>
        ))}
        {labels.length === 0 && <li className="text-sm text-muted">No labels yet.</li>}
      </ul>
      <form
        className="flex items-end gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await run(() => api(base, { method: "POST", json: { name, color } }))) setName("");
        }}
      >
        <input aria-label="Label name" placeholder="Label name" required value={name} onChange={(e) => setName(e.target.value)} className="rounded border border-line bg-surface-2 px-2 py-1.5 text-sm" />
        <input aria-label="Label color" type="color" value={color} onChange={(e) => setColor(e.target.value)} className="h-9 w-10 rounded border border-line bg-surface-2" />
        <Button type="submit" variant="ghost">Add label</Button>
      </form>
    </div>
  );
}
