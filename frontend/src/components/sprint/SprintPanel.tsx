"use client";

import { useDraggable, useDroppable } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical } from "lucide-react";

import { TYPE_ICON } from "@/components/board/TaskCard";
import type { Sprint, Task } from "@/lib/types";

export const BACKLOG = "backlog";

export function TaskRow({
  task,
  destinations,
  disabled,
  onOpen,
  onMove,
}: {
  task: Task;
  destinations: { id: string; name: string }[];
  disabled: boolean;
  onOpen: (key: string) => void;
  onMove: (taskKey: string, sprintId: string) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: task.key, disabled });
  const Icon = TYPE_ICON[task.type];
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), opacity: isDragging ? 0.5 : 1 }}
      className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-line bg-surface px-2 py-1.5 text-sm last:border-0"
    >
      {!disabled && (
        <button type="button" className="cursor-grab text-muted-foreground" aria-label={`Drag ${task.key}`} {...attributes} {...listeners}>
          <GripVertical size={14} aria-hidden />
        </button>
      )}
      <Icon size={12} className="text-muted-foreground" aria-hidden />
      <span className="w-16 shrink-0 text-xs text-muted-foreground">{task.key}</span>
      {/* at least 10rem: on a phone the title moves to its own line and wraps; wider, it stays on one line */}
      <button type="button" className="min-w-40 flex-1 text-left break-words hover:text-cyan-ink sm:truncate" onClick={() => onOpen(task.key)}>
        {task.title}
      </button>
      <span className={`text-[11px] ${task.column_category === "done" ? "text-green-ink" : "text-muted-foreground"}`}>
        {task.column_category === "done" ? "done" : ""}
      </span>
      <span className="w-8 text-right text-xs text-muted-foreground" aria-label={`${task.story_points ?? 0} points`}>{task.story_points ?? "–"}</span>
      {!disabled && (
        <select
          aria-label={`Move ${task.key} to`}
          className="rounded border border-line bg-surface-2 px-1 py-0.5 text-xs"
          value=""
          onChange={(e) => e.target.value && onMove(task.key, e.target.value)}
        >
          <option value="">Move…</option>
          {destinations.map((d) => (
            <option key={d.id} value={d.id}>{d.name}</option>
          ))}
        </select>
      )}
    </li>
  );
}

export function DropZone({
  id,
  title,
  meta,
  actions,
  tasks,
  top,
  children,
}: {
  id: string;
  title: React.ReactNode;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  tasks: Task[];
  top?: React.ReactNode;
  children: React.ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `sprint:${id}` });
  const points = tasks.reduce((n, t) => n + (t.story_points ?? 0), 0);
  return (
    <section ref={setNodeRef} className={`card overflow-hidden ${isOver ? "border-cyan glow-box" : ""}`} aria-label={typeof title === "string" ? title : undefined}>
      <header className="flex flex-wrap items-center gap-3 border-b border-line bg-surface-2 px-3 py-2">
        <h2 className="text-sm text-cyan-ink">{title}</h2>
        <span className="text-xs text-muted-foreground">{tasks.length} tasks · {points} points</span>
        {meta}
        <span className="flex-1" />
        {actions}
      </header>
      {top}
      <ul className="min-h-10">{children}</ul>
      {tasks.length === 0 && <p className="px-3 py-3 text-xs text-muted-foreground">Drag tasks here.</p>}
    </section>
  );
}

export function sprintLabel(s: Sprint): string {
  return `${s.name}${s.state === "active" ? " (active)" : ""}`;
}
