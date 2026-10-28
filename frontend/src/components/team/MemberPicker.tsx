"use client";

import { Check } from "lucide-react";
import { useMemo, useState } from "react";

import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/shadcn/command";
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
      {/* a searchable list: type to filter, arrows to move, Enter or a click to tick; several people, then Save */}
      <Command shouldFilter={false} label="Search people" className="rounded border border-line bg-surface-2">
        <CommandInput placeholder="Search people" value={q} onValueChange={setQ} />
        <CommandList className="max-h-72">
          <CommandEmpty>No one matches.</CommandEmpty>
          {visible.map((u) => {
            const on = chosen.has(u.id);
            return (
              <CommandItem key={u.id} value={u.id} aria-checked={on} onSelect={() => toggle(u.id)} className="gap-2">
                <span
                  aria-hidden
                  className={`grid size-4 shrink-0 place-items-center rounded-sm border ${on ? "border-cyan bg-cyan text-on-accent" : "border-line"}`}
                >
                  {on && <Check size={12} />}
                </span>
                <Avatar name={u.name} />
                <span className="min-w-0 flex-1 truncate">{u.name}</span>
                <span className="truncate text-xs text-muted-foreground">{u.email}</span>
              </CommandItem>
            );
          })}
        </CommandList>
      </Command>
      <Button disabled={saving} onClick={() => onSave(users.filter((u) => chosen.has(u.id)).map((u) => u.id))}>
        Save members
      </Button>
    </div>
  );
}
