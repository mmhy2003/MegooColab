"use client";

import { Plus } from "lucide-react";
import { useState } from "react";

import type { TaskType } from "@/lib/types";

const TYPES: TaskType[] = ["story", "task", "bug", "epic"];

/** Adds items straight to the backlog (no sprint). Epics are created here too. */
export function BacklogQuickCreate({ onCreate }: { onCreate: (title: string, type: TaskType) => Promise<void> }) {
  const [title, setTitle] = useState("");
  const [type, setType] = useState<TaskType>("story");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="flex items-center gap-2 border-b border-line px-2 py-1.5"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!title.trim()) return;
        setBusy(true);
        try {
          await onCreate(title.trim(), type);
          setTitle("");
        } finally {
          setBusy(false);
        }
      }}
    >
      <Plus size={14} className="text-muted-foreground" aria-hidden />
      <select
        aria-label="New item type"
        value={type}
        onChange={(e) => setType(e.target.value as TaskType)}
        className="rounded border border-line bg-surface-2 px-1 py-0.5 text-xs"
      >
        {TYPES.map((t) => (
          <option key={t} value={t}>{t}</option>
        ))}
      </select>
      <input
        aria-label="New backlog item"
        placeholder="Add to backlog"
        disabled={busy}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        className="min-w-0 flex-1 rounded border border-transparent bg-transparent px-1 py-1 text-sm placeholder:text-muted-foreground focus:border-cyan focus:outline-none"
      />
    </form>
  );
}
