"use client";

import { CheckCircle2, Circle } from "lucide-react";
import { useState } from "react";

import type { Task } from "@/lib/types";

export function Subtasks({
  subtasks,
  disabled,
  onOpen,
  onAdd,
}: {
  subtasks: Task[];
  disabled: boolean;
  onOpen: (key: string) => void;
  onAdd: (title: string) => Promise<void>;
}) {
  const [title, setTitle] = useState("");
  return (
    <div className="space-y-2">
      <ul className="space-y-1">
        {subtasks.map((s) => (
          <li key={s.id}>
            <button type="button" className="flex w-full items-center gap-2 rounded px-1 py-1 text-left text-sm hover:bg-surface-2" onClick={() => onOpen(s.key)}>
              {s.column_category === "done" ? (
                <CheckCircle2 size={14} className="text-green-ink" aria-label="done" />
              ) : (
                <Circle size={14} className="text-muted-foreground" aria-label="open" />
              )}
              <span className="text-xs text-muted-foreground">{s.key}</span>
              <span className={s.column_category === "done" ? "line-through opacity-70" : ""}>{s.title}</span>
            </button>
          </li>
        ))}
      </ul>
      {!disabled && (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (!title.trim()) return;
            await onAdd(title.trim());
            setTitle("");
          }}
        >
          <input
            aria-label="New subtask"
            placeholder="Add a subtask"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded border border-line bg-surface-2 px-2 py-1 text-sm"
          />
        </form>
      )}
    </div>
  );
}
