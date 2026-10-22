"use client";

import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";
import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Column, Task } from "@/lib/types";

import { BoardColumn } from "./Column";
import { moveTarget } from "./moveTarget";
import { TaskCardView } from "./TaskCard";

const STEP = 1024;

function positionFor(list: Task[], target: { before_key?: string; after_key?: string }): number {
  const before = list.find((t) => t.key === target.before_key)?.position;
  const after = list.find((t) => t.key === target.after_key)?.position;
  if (before != null && after != null) return (before + after) / 2;
  if (before != null) return before + STEP;
  if (after != null) return after - STEP;
  return STEP;
}

export function Board({
  projectKey,
  columns,
  tasks,
  queryKey,
  userNames,
  canWrite,
  onOpen,
  onCreate,
}: {
  projectKey: string;
  columns: Column[];
  tasks: Task[];
  queryKey: QueryKey;
  userNames: Map<string, string>;
  canWrite: boolean;
  onOpen: (key: string) => void;
  onCreate: (columnId: string, title: string) => Promise<void>;
}) {
  const client = useQueryClient();
  const [dragging, setDragging] = useState<Task | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const byColumn = useMemo(() => {
    const map = new Map<string, Task[]>(columns.map((c) => [c.id, []]));
    for (const t of tasks) map.get(t.column_id)?.push(t);
    for (const list of map.values()) list.sort((a, b) => a.position - b.position);
    return map;
  }, [columns, tasks]);

  async function onDragEnd(event: DragEndEvent) {
    setDragging(null);
    const { active, over } = event;
    if (!canWrite || !over) return;
    const task = tasks.find((t) => t.key === active.id);
    if (!task) return;
    const overId = String(over.id);
    let columnId: string;
    let index: number;
    if (overId.startsWith("column:")) {
      columnId = overId.slice("column:".length);
      index = byColumn.get(columnId)?.length ?? 0;
    } else {
      const overTask = tasks.find((t) => t.key === overId);
      if (!overTask) return;
      columnId = overTask.column_id;
      index = (byColumn.get(columnId) ?? []).findIndex((t) => t.key === overId);
    }
    const list = byColumn.get(columnId) ?? [];
    if (columnId === task.column_id && list.findIndex((t) => t.key === task.key) === index) return;

    const target = moveTarget(list, index, task.key);
    const column = columns.find((c) => c.id === columnId)!;
    const snapshot = client.getQueryData<Task[]>(queryKey);
    client.setQueryData<Task[]>(queryKey, (old) =>
      old?.map((t) =>
        t.key === task.key
          ? { ...t, column_id: columnId, column_category: column.category, position: positionFor(list, target) }
          : t,
      ),
    );
    try {
      setError(null);
      await api(`/api/tasks/${task.key}/move`, { method: "POST", json: { column_id: columnId, ...target } });
    } catch (err) {
      client.setQueryData(queryKey, snapshot);
      setError(errorMessage(err));
    } finally {
      void client.invalidateQueries({ queryKey: ["tasks", projectKey] });
    }
  }

  return (
    <div className="space-y-2">
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={(e: DragStartEvent) => setDragging(tasks.find((t) => t.key === e.active.id) ?? null)}
        onDragCancel={() => setDragging(null)}
        onDragEnd={onDragEnd}
      >
        <div className="flex gap-3 overflow-x-auto pb-4">
          {columns.map((c) => (
            <BoardColumn
              key={c.id}
              column={c}
              tasks={byColumn.get(c.id) ?? []}
              userNames={userNames}
              canWrite={canWrite}
              onOpen={onOpen}
              onCreate={(title) => onCreate(c.id, title)}
            />
          ))}
        </div>
        <DragOverlay>
          {dragging && (
            <TaskCardView
              task={dragging}
              dragging
              assigneeName={dragging.assignee_user_id ? userNames.get(dragging.assignee_user_id) : undefined}
            />
          )}
        </DragOverlay>
      </DndContext>
    </div>
  );
}
