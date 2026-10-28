"use client";

import { useMemo, useState } from "react";

import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import type { User } from "@/lib/types";

export function MemberPicker({
  users,
  selected,
  onSave,
  saving = false,
}: {
  users: User[];
  selected: string[];
  onSave: (ids: string[]) => void;
  saving?: boolean;
}) {
  const [chosen, setChosen] = useState(() => new Set(selected));
  const [q, setQ] = useState("");

  const visible = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return users.filter(
      (u) =>
        (u.status !== "deactivated" || chosen.has(u.id)) &&
        (!needle || u.name.toLowerCase().includes(needle) || u.email.toLowerCase().includes(needle)),
    );
  }, [users, q, chosen]);

  const toggle = (id: string) =>
    setChosen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="space-y-3">
      <input
        aria-label="Search people"
        placeholder="Search people"
        className="w-full rounded border border-line bg-surface-2 px-3 py-2 text-sm"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <ul className="max-h-72 space-y-1 overflow-y-auto">
        {visible.map((u) => (
          <li key={u.id}>
            <label className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-surface-2">
              <input type="checkbox" aria-label={u.name} checked={chosen.has(u.id)} onChange={() => toggle(u.id)} />
              <Avatar name={u.name} />
              <span className="flex-1">{u.name}</span>
              <span className="text-xs text-muted-foreground">{u.email}</span>
            </label>
          </li>
        ))}
      </ul>
      <Button disabled={saving} onClick={() => onSave(users.filter((u) => chosen.has(u.id)).map((u) => u.id))}>
        Save members
      </Button>
    </div>
  );
}
