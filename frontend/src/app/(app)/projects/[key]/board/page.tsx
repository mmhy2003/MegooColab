"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";

import { Board } from "@/components/board/Board";
import { BoardFilters, type BoardFilterState } from "@/components/board/BoardFilters";
import { TaskDrawer } from "@/components/task/TaskDrawer";
import { api } from "@/lib/api";
import { useMe } from "@/lib/me";
import { useColumns, useLabels, useProject, useSprints, useTasks, useUsers } from "@/lib/project";
import { qk } from "@/lib/queries";
import type { Task } from "@/lib/types";

function BoardPage() {
  const { key } = useParams<{ key: string }>();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const client = useQueryClient();
  const { data: me } = useMe();
  const project = useProject(key);
  const columns = useColumns(key);
  const labels = useLabels(key);
  const users = useUsers();
  const sprintsOn = project.data?.sprints_enabled ?? false;
  const sprints = useSprints(key, sprintsOn);
  const activeSprint = sprints.data?.find((s) => s.state === "active");
  const [filters, setFilters] = useState<BoardFilterState>({});
  const taskFilters = { ...filters, sprint: sprintsOn ? "active" : undefined };
  const tasks = useTasks(key, taskFilters);
  const epics = useTasks(key, { type: "epic" });
  const openKey = params.get("task");

  const userNames = useMemo(() => new Map(users.data?.map((u) => [u.id, u.name])), [users.data]);
  const boardTasks = useMemo(
    () => (tasks.data ?? []).filter((t: Task) => t.type !== "epic" && t.type !== "subtask"),
    [tasks.data],
  );

  const setOpen = (taskKey: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (taskKey) next.set("task", taskKey);
    else next.delete("task");
    router.replace(`${pathname}${next.size ? `?${next}` : ""}`, { scroll: false });
  };

  if (!project.data || !columns.data) return null;
  const canWrite = me?.role !== "viewer";

  if (sprintsOn && sprints.data && !activeSprint) {
    return (
      <div className="card mx-auto mt-6 max-w-md p-6 text-center text-sm">
        <p>No active sprint.</p>
        <Link href={`/projects/${key}/backlog`} className="mt-2 inline-block">Plan one in Backlog</Link>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <BoardFilters value={filters} onChange={setFilters} users={users.data ?? []} labels={labels.data ?? []} epics={epics.data ?? []} />
        {activeSprint && (
          <p className="text-xs text-muted">
            <span className="text-cyan-ink">{activeSprint.name}</span> · ends {activeSprint.end_date}
          </p>
        )}
      </div>
      <Board
        projectKey={key}
        columns={columns.data}
        tasks={boardTasks}
        queryKey={qk.tasks(key, taskFilters)}
        userNames={userNames}
        canWrite={canWrite}
        onOpen={setOpen}
        onCreate={async (columnId, title) => {
          const task = await api<Task>(`/api/projects/${key}/tasks`, {
            method: "POST",
            json: { title, type: "task", column_id: columnId },
          });
          // a card created on the sprint board belongs to that sprint, or it would vanish
          if (activeSprint) {
            await api(`/api/tasks/${task.key}/sprint`, { method: "PUT", json: { sprint_id: activeSprint.id } });
          }
          await client.invalidateQueries({ queryKey: ["tasks", key] });
        }}
      />
      {openKey && <TaskDrawer taskKey={openKey} onClose={() => setOpen(null)} onOpenTask={setOpen} />}
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <BoardPage />
    </Suspense>
  );
}
