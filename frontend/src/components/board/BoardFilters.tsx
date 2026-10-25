"use client";

import { Search } from "lucide-react";

import type { Label, Task, User } from "@/lib/types";

export type BoardFilterState = { assignee?: string; label?: string; epic?: string; q?: string; needs_you?: string };

const FIELD = "rounded border border-line bg-surface-2 px-2 py-1.5 text-sm";

export function BoardFilters({
  value,
  onChange,
  users,
  labels,
  epics,
}: {
  value: BoardFilterState;
  onChange: (v: BoardFilterState) => void;
  users: User[];
  labels: Label[];
  epics: Task[];
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="relative">
        <span className="sr-only">Search tasks</span>
        <Search size={14} className="absolute top-2.5 left-2 text-muted" aria-hidden />
        <input
          className={`${FIELD} pl-7`}
          placeholder="Search"
          value={value.q ?? ""}
          onChange={(e) => onChange({ ...value, q: e.target.value || undefined })}
        />
      </label>
      <select aria-label="Filter by assignee" className={FIELD} value={value.assignee ?? ""} onChange={(e) => onChange({ ...value, assignee: e.target.value || undefined })}>
        <option value="">Anyone</option>
        {users.map((u) => (
          <option key={u.id} value={u.id}>{u.name}</option>
        ))}
      </select>
      <select aria-label="Filter by label" className={FIELD} value={value.label ?? ""} onChange={(e) => onChange({ ...value, label: e.target.value || undefined })}>
        <option value="">Any label</option>
        {labels.map((l) => (
          <option key={l.id} value={l.id}>{l.name}</option>
        ))}
      </select>
      <select aria-label="Filter by epic" className={FIELD} value={value.epic ?? ""} onChange={(e) => onChange({ ...value, epic: e.target.value || undefined })}>
        <option value="">Any epic</option>
        {epics.map((t) => (
          <option key={t.id} value={t.id}>{t.key} {t.title}</option>
        ))}
      </select>
      <label className="inline-flex items-center gap-1.5 text-sm">
        <input
          type="checkbox"
          checked={value.needs_you === "true"}
          onChange={(e) => onChange({ ...value, needs_you: e.target.checked ? "true" : undefined })}
        />
        Needs you
      </label>
    </div>
  );
}
