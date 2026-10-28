"use client";

import { Plus } from "lucide-react";
import { useState } from "react";

export function QuickCreate({ columnName, onCreate }: { columnName: string; onCreate: (title: string) => Promise<void> }) {
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="flex items-center gap-1 px-2"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!title.trim()) return;
        setBusy(true);
        try {
          await onCreate(title.trim());
          setTitle("");
        } finally {
          setBusy(false);
        }
      }}
    >
      <Plus size={14} className="text-muted-foreground" aria-hidden />
      <input
        aria-label={`New task in ${columnName}`}
        placeholder="Add a task"
        disabled={busy}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        className="min-w-0 flex-1 rounded border border-transparent bg-transparent px-1 py-1 text-sm placeholder:text-muted-foreground focus:border-cyan focus:bg-surface focus:outline-none"
      />
    </form>
  );
}
