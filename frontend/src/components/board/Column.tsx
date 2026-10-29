"use client";

import { useDroppable } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";

import { CATEGORY_LABEL } from "@/components/project/ColumnEditor";
import type { Column as ColumnT, Task } from "@/lib/types";

import { QuickCreate } from "./QuickCreate";
import { SortableTaskCard } from "./TaskCard";

export function BoardColumn({
  column,
  tasks,
  userNames,
  canWrite,
  onOpen,
  onCreate,
}: {
  column: ColumnT;
  tasks: Task[];
  userNames: Map<string, string>;
  canWrite: boolean;
  onOpen: (key: string) => void;
  onCreate: (title: string) => Promise<void>;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `column:${column.id}`, data: { columnId: column.id } });
  return (
    <section
      aria-label={`${column.name} column`}
      className={`flex w-72 shrink-0 flex-col rounded border bg-surface-2/50 ${isOver ? "border-cyan" : "border-line"}`}
    >
      <header className="flex items-center gap-2 px-3 pt-3 pb-2">
        <h2 className="font-display text-[11px] tracking-widest text-muted-foreground uppercase">{column.name}</h2>
        <span className="text-xs text-pink">{tasks.length}</span>
        <span className="sr-only">({CATEGORY_LABEL[column.category]})</span>
      </header>
      {canWrite && <QuickCreate columnName={column.name} onCreate={onCreate} />}
      <SortableContext id={column.id} items={tasks.map((t) => t.key)} strategy={verticalListSortingStrategy}>
        <ul ref={setNodeRef} className="flex min-h-24 flex-1 flex-col gap-2 p-2">
          {tasks.map((t) => (
            <SortableTaskCard
              key={t.key}
              task={t}
              assigneeName={t.assignee_user_id ? userNames.get(t.assignee_user_id) : undefined}
              canDrag={canWrite}
              onOpen={() => onOpen(t.key)}
            />
          ))}
        </ul>
      </SortableContext>
    </section>
  );
}
