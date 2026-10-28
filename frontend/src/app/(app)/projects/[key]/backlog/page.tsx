"use client";

import { DndContext, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";

import { BacklogQuickCreate } from "@/components/sprint/BacklogQuickCreate";
import { CompleteSprintDialog } from "@/components/sprint/CompleteSprintDialog";
import { DeleteSprintButton } from "@/components/sprint/DeleteSprintButton";
import { NewSprintDialog } from "@/components/sprint/NewSprintDialog";
import { BACKLOG, DropZone, TaskRow, sprintLabel } from "@/components/sprint/SprintPanel";
import { TaskDrawer } from "@/components/task/TaskDrawer";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { canManage, useMe } from "@/lib/me";
import { useProject, useSprints, useTasks } from "@/lib/project";
import { qk } from "@/lib/queries";
import type { Sprint, Task } from "@/lib/types";

const SPRINTABLE = new Set(["story", "task", "bug"]);

function BacklogPage() {
  const { key } = useParams<{ key: string }>();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const client = useQueryClient();
  const { data: me } = useMe();
  const project = useProject(key);
  const sprints = useSprints(key, project.data?.sprints_enabled ?? false);
  const tasks = useTasks(key);
  const [epic, setEpic] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [completing, setCompleting] = useState<Sprint | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }), useSensor(KeyboardSensor));
  const disabled = me?.role === "viewer";
  const canPlan = canManage(me); // sprint create/start/complete is for managers and admins
  const openKey = params.get("task");

  const all = tasks.data ?? [];
  const epics = all.filter((t) => t.type === "epic");
  const visible = all.filter((t) => SPRINTABLE.has(t.type) && (!epic || t.parent_id === epic));
  const open = (sprints.data ?? []).filter((s) => s.state !== "completed");
  const grouped = useMemo(() => {
    const m = new Map<string, Task[]>([[BACKLOG, []], ...open.map((s) => [s.id, []] as [string, Task[]])]);
    for (const t of visible) m.get(t.sprint_id ?? BACKLOG)?.push(t);
    for (const list of m.values()) list.sort((a, b) => a.position - b.position);
    return m;
  }, [visible, open]);

  const destinations = [...open.map((s) => ({ id: s.id, name: sprintLabel(s) })), { id: BACKLOG, name: "Backlog" }];
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["tasks", key] }),
      client.invalidateQueries({ queryKey: qk.sprints(key) }),
    ]);
  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      await refresh();
    }
  };
  const moveTask = (taskKey: string, dest: string) =>
    run(() => api(`/api/tasks/${taskKey}/sprint`, { method: "PUT", json: { sprint_id: dest === BACKLOG ? null : dest } }));
  const setOpen = (taskKey: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (taskKey) next.set("task", taskKey);
    else next.delete("task");
    router.replace(`${pathname}${next.size ? `?${next}` : ""}`, { scroll: false });
  };

  function onDragEnd(e: DragEndEvent) {
    const dest = e.over ? String(e.over.id).replace(/^sprint:/, "") : null;
    const task = all.find((t) => t.key === e.active.id);
    if (!dest || !task || (task.sprint_id ?? BACKLOG) === dest) return;
    void moveTask(task.key, dest);
  }

  if (!project.data) return null;
  const hasActive = open.some((s) => s.state === "active");

  const rows = (list: Task[]) =>
    list.map((t) => (
      <TaskRow
        key={t.key}
        task={t}
        disabled={disabled}
        destinations={destinations.filter((d) => d.id !== (t.sprint_id ?? BACKLOG))}
        onOpen={setOpen}
        onMove={moveTask}
      />
    ));

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[12rem_minmax(0,1fr)]">
      <aside aria-label="Epics" className="space-y-1">
        <h2 className="mb-1 text-[11px] tracking-widest text-muted-foreground uppercase">Epics</h2>
        <button type="button" aria-pressed={epic === null} onClick={() => setEpic(null)} className={`block w-full rounded px-2 py-1 text-left text-sm ${epic === null ? "bg-surface-2 text-cyan-ink" : "text-muted-foreground"}`}>
          All issues
        </button>
        {epics.map((e) => (
          <button key={e.id} type="button" aria-pressed={epic === e.id} onClick={() => setEpic(e.id)} className={`block w-full truncate rounded px-2 py-1 text-left text-sm ${epic === e.id ? "bg-surface-2 text-cyan-ink" : "text-muted-foreground"}`}>
            {e.title}
          </button>
        ))}
      </aside>
      <div className="space-y-4">
        {error && <p role="alert" className="text-sm text-pink">{error}</p>}
        <DndContext sensors={sensors} onDragEnd={onDragEnd}>
          {open.map((s) => {
            const list = grouped.get(s.id) ?? [];
            return (
              <DropZone
                key={s.id}
                id={s.id}
                title={sprintLabel(s)}
                tasks={list}
                meta={<span className="text-xs text-muted-foreground">{s.start_date} → {s.end_date}{s.goal ? ` · ${s.goal}` : ""}</span>}
                actions={
                  canPlan && (
                    <>
                      {s.state === "active" ? (
                        <Button variant="ghost" onClick={() => setCompleting(s)}>Complete</Button>
                      ) : (
                        <Button variant="ghost" disabled={hasActive} title={hasActive ? "Finish the active sprint first" : undefined} onClick={() => run(() => api(`/api/sprints/${s.id}/start`, { method: "POST" }))}>
                          Start
                        </Button>
                      )}
                      <DeleteSprintButton sprint={s} taskCount={all.filter((t) => t.sprint_id === s.id).length} />
                    </>
                  )
                }
              >
                {rows(list)}
              </DropZone>
            );
          })}
          <DropZone
            id={BACKLOG}
            title="Backlog"
            tasks={grouped.get(BACKLOG) ?? []}
            top={
              !disabled && (
                <BacklogQuickCreate
                  onCreate={(title, type) =>
                    run(() => api(`/api/projects/${key}/tasks`, { method: "POST", json: { title, type } }))
                  }
                />
              )
            }
            actions={
              canPlan && (
                <Button variant="ghost" onClick={() => setCreating(true)}>
                  <Plus size={14} aria-hidden /> New sprint
                </Button>
              )
            }
          >
            {rows(grouped.get(BACKLOG) ?? [])}
          </DropZone>
        </DndContext>
      </div>
      {creating && (
        <NewSprintDialog
          suggestedName={`Sprint ${(sprints.data?.length ?? 0) + 1}`}
          onClose={() => setCreating(false)}
          onCreate={async (body) => {
            await api(`/api/projects/${key}/sprints`, { method: "POST", json: body });
            await refresh();
          }}
        />
      )}
      {completing && (
        <CompleteSprintDialog
          sprint={completing}
          openCount={all.filter((t) => t.sprint_id === completing.id && t.column_category !== "done").length}
          planned={open.filter((s) => s.state === "planned")}
          onClose={() => setCompleting(null)}
          onConfirm={(move_open_to) => {
            const id = completing.id;
            setCompleting(null);
            void run(() => api(`/api/sprints/${id}/complete`, { method: "POST", json: { move_open_to } }));
          }}
        />
      )}
      {openKey && <TaskDrawer taskKey={openKey} onClose={() => setOpen(null)} onOpenTask={setOpen} />}
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <BacklogPage />
    </Suspense>
  );
}
