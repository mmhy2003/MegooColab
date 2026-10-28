"use client";

import { X } from "lucide-react";
import { useState } from "react";

import type { Task } from "@/lib/types";

const KIND_LABEL = { blocks: "blocks", blocked_by: "is blocked by", relates: "relates to" } as const;

export function Links({
  task,
  disabled,
  onOpen,
  onAdd,
  onRemove,
}: {
  task: Task;
  disabled: boolean;
  onOpen: (key: string) => void;
  onAdd: (targetKey: string, kind: "blocks" | "relates") => Promise<void>;
  onRemove: (linkId: string) => void;
}) {
  const [target, setTarget] = useState("");
  const [kind, setKind] = useState<"blocks" | "relates">("relates");
  const links = task.links ?? [];
  return (
    <div className="space-y-2">
      <ul className="space-y-1">
        {links.map((l) => (
          <li key={l.id} className="flex items-center gap-2 text-sm">
            <span className="w-28 shrink-0 text-xs text-muted-foreground">{KIND_LABEL[l.kind]}</span>
            <button type="button" className="min-w-0 flex-1 truncate text-left hover:text-cyan-ink" onClick={() => onOpen(l.task.key)}>
              <span className="text-xs text-muted-foreground">{l.task.key}</span> {l.task.title}
            </button>
            {!disabled && (
              <button type="button" className="icon-btn h-6 w-6" aria-label={`Remove link to ${l.task.key}`} onClick={() => onRemove(l.id)}>
                <X size={12} aria-hidden />
              </button>
            )}
          </li>
        ))}
        {links.length === 0 && <li className="text-xs text-muted-foreground">No linked tasks.</li>}
      </ul>
      {!disabled && (
        <form
          className="flex gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!target.trim()) return;
            await onAdd(target.trim().toUpperCase(), kind);
            setTarget("");
          }}
        >
          <select aria-label="Link type" value={kind} onChange={(e) => setKind(e.target.value as "blocks" | "relates")} className="rounded border border-line bg-surface-2 px-1 py-1 text-xs">
            <option value="relates">relates to</option>
            <option value="blocks">blocks</option>
          </select>
          <input aria-label="Task key to link" placeholder="e.g. PAY-7" value={target} onChange={(e) => setTarget(e.target.value)} className="min-w-0 flex-1 rounded border border-line bg-surface-2 px-2 py-1 text-sm" />
        </form>
      )}
    </div>
  );
}
