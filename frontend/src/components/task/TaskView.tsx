"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { TYPE_ICON } from "@/components/board/TaskCard";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useMe } from "@/lib/me";
import { useColumns, useLabels, useProject, useSprints, useTasks, useUsers } from "@/lib/project";
import { qk } from "@/lib/queries";
import type { ActivityItem, Attachment, Task } from "@/lib/types";

import { ActivityThread } from "./ActivityThread";
import { Attachments } from "./Attachments";
import { CommentBox } from "./CommentBox";
import { Description } from "./Description";
import { Links } from "./Links";
import { Subtasks } from "./Subtasks";
import { TaskFields } from "./TaskFields";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-[11px] tracking-widest text-muted uppercase">{title}</h3>
      {children}
    </section>
  );
}

export function TaskView({
  taskKey,
  onOpenTask,
  onDeleted,
  headerExtra,
}: {
  taskKey: string;
  onOpenTask: (key: string) => void;
  onDeleted: () => void;
  headerExtra?: React.ReactNode;
}) {
  const projectKey = taskKey.split("-")[0].toUpperCase();
  const client = useQueryClient();
  const { data: me } = useMe();
  const task = useQuery({ queryKey: qk.task(taskKey), queryFn: () => api<Task>(`/api/tasks/${taskKey}`) });
  const activity = useQuery({ queryKey: qk.activity(taskKey), queryFn: () => api<ActivityItem[]>(`/api/tasks/${taskKey}/activity`) });
  const attachments = useQuery({ queryKey: qk.attachments(taskKey), queryFn: () => api<Attachment[]>(`/api/tasks/${taskKey}/attachments`) });
  const project = useProject(projectKey);
  const columns = useColumns(projectKey);
  const labels = useLabels(projectKey);
  const users = useUsers();
  const sprints = useSprints(projectKey, project.data?.sprints_enabled ?? false);
  const all = useTasks(projectKey);
  const [error, setError] = useState<string | null>(null);

  const userNames = useMemo(() => new Map(users.data?.map((u) => [u.id, u.name])), [users.data]);
  const columnNames = useMemo(() => new Map(columns.data?.map((c) => [c.id, c.name])), [columns.data]);

  if (task.error) return <p className="p-4 text-sm text-pink">{errorMessage(task.error)}</p>;
  const t = task.data;
  if (!t || !columns.data) return <p className="p-4 text-sm text-muted">Loading…</p>;

  const disabled = me?.role === "viewer";
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: qk.task(taskKey) }),
      client.invalidateQueries({ queryKey: qk.activity(taskKey) }),
      client.invalidateQueries({ queryKey: ["tasks", projectKey] }),
    ]);
  };
  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  const subtasks = (all.data ?? []).filter((x) => x.parent_id === t.id && x.type === "subtask");
  const parents = (all.data ?? []).filter((x) =>
    t.type === "subtask" ? ["story", "task", "bug"].includes(x.type) && x.id !== t.id : x.type === "epic",
  );
  const TypeIcon = TYPE_ICON[t.type];

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-start gap-2 border-b border-line p-4">
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1.5 text-xs text-muted">
            <TypeIcon size={12} aria-hidden /> {t.key}
          </p>
          <input
            aria-label="Title"
            key={t.title}
            defaultValue={t.title}
            disabled={disabled}
            className="mt-1 w-full rounded border border-transparent bg-transparent px-1 font-display text-base text-fg hover:border-line focus:border-cyan focus:outline-none"
            onBlur={(e) => {
              const title = e.target.value.trim();
              if (title && title !== t.title) void run(() => api(`/api/tasks/${t.key}`, { method: "PATCH", json: { title } }));
            }}
          />
        </div>
        {!disabled && (
          <button
            type="button"
            className="icon-btn hover:text-pink"
            aria-label="Delete task"
            onClick={async () => {
              if (!confirm(`Delete ${t.key}?${t.type === "epic" ? " Its tasks stay, without an epic." : " Its subtasks are deleted too."}`)) return;
              try {
                await api(`/api/tasks/${t.key}`, { method: "DELETE" });
                await client.invalidateQueries({ queryKey: ["tasks", projectKey] });
                onDeleted();
              } catch (err) {
                setError(errorMessage(err));
              }
            }}
          >
            <Trash2 size={16} aria-hidden />
          </button>
        )}
        {headerExtra}
      </header>
      {error && <p role="alert" className="px-4 pt-2 text-sm text-pink">{error}</p>}
      <div className="grid min-h-0 flex-1 gap-6 overflow-y-auto p-4 lg:grid-cols-[1fr_17rem]">
        <div className="min-w-0 space-y-6">
          <Section title="Description">
            <Description value={t.description_md} disabled={disabled} onSave={(md) => run(() => api(`/api/tasks/${t.key}`, { method: "PATCH", json: { description_md: md } }))} />
          </Section>
          {t.type !== "subtask" && t.type !== "epic" && (
            <Section title={`Subtasks (${t.subtask_done_count}/${t.subtask_count})`}>
              <Subtasks
                subtasks={subtasks}
                disabled={disabled}
                onOpen={onOpenTask}
                onAdd={(title) => run(() => api(`/api/projects/${projectKey}/tasks`, { method: "POST", json: { title, type: "subtask", parent_id: t.id } }))}
              />
            </Section>
          )}
          <Section title="Linked tasks">
            <Links
              task={t}
              disabled={disabled}
              onOpen={onOpenTask}
              onAdd={(target_key, kind) => run(() => api(`/api/tasks/${t.key}/links`, { method: "POST", json: { target_key, kind } }))}
              onRemove={(id) => run(() => api(`/api/tasks/${t.key}/links/${id}`, { method: "DELETE" }))}
            />
          </Section>
          <Section title="Attachments">
            <Attachments
              items={attachments.data ?? []}
              disabled={disabled}
              onUpload={async (file) => {
                const form = new FormData();
                form.append("file", file);
                await run(() => api(`/api/tasks/${t.key}/attachments`, { method: "POST", body: form }));
                await client.invalidateQueries({ queryKey: qk.attachments(taskKey) });
              }}
              onDelete={async (id) => {
                await run(() => api(`/api/attachments/${id}`, { method: "DELETE" }));
                await client.invalidateQueries({ queryKey: qk.attachments(taskKey) });
              }}
            />
          </Section>
          <Section title="Activity">
            <ActivityThread items={activity.data ?? []} columnNames={columnNames} userNames={userNames} />
            {!disabled && <CommentBox onSubmit={(body_md) => run(() => api(`/api/tasks/${t.key}/comments`, { method: "POST", json: { body_md } }))} />}
          </Section>
        </div>
        <aside className="space-y-4">
          <TaskFields
            task={t}
            columns={columns.data}
            users={users.data ?? []}
            labels={labels.data ?? []}
            parents={parents}
            sprints={project.data?.sprints_enabled ? sprints.data : undefined}
            meId={me?.id}
            disabled={disabled}
            onPatch={(patch) => void run(() => api(`/api/tasks/${t.key}`, { method: "PATCH", json: patch }))}
            onMove={(column_id) => void run(() => api(`/api/tasks/${t.key}/move`, { method: "POST", json: { column_id } }))}
            onSprint={(sprint_id) => void run(() => api(`/api/tasks/${t.key}/sprint`, { method: "PUT", json: { sprint_id } }))}
            onWatch={(watch) => void run(() => api(`/api/tasks/${t.key}/watch`, { method: watch ? "PUT" : "DELETE" }))}
          />
          <p className="text-[11px] text-muted">
            Reported by {t.reporter_id ? userNames.get(t.reporter_id) ?? "someone" : "someone"} ·{" "}
            {new Date(t.created_at).toLocaleDateString()}
          </p>
        </aside>
      </div>
    </div>
  );
}
