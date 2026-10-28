"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { TYPE_ICON } from "@/components/board/TaskCard";
import { useProjectAgents } from "@/lib/agents";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useMe } from "@/lib/me";
import { useColumns, useLabels, useProject, useSprints, useTasks, useUsers } from "@/lib/project";
import { qk } from "@/lib/queries";
import type { ActivityItem, Attachment, Task } from "@/lib/types";

import { DocumentView } from "@/components/workflow/DocumentView";
import { Decisions } from "@/components/workflow/Decisions";
import { MockupPanel } from "@/components/workflow/MockupPanel";
import { KbReferences } from "@/components/kb/KbReferences";
import { TaskQuestions, WaitingBadge } from "@/components/questions/TaskQuestions";
import { WorkflowPanel } from "@/components/workflow/WorkflowPanel";
import { useMockups, useRunRecords, useWorkflow } from "@/lib/workflow";
import { Hint } from "@/components/ui/Hint";
import { useConfirm } from "@/components/ui/ConfirmDialog";

import { ActivityThread } from "./ActivityThread";
import { Attachments } from "./Attachments";
import { CommentBox } from "./CommentBox";
import { Description } from "./Description";
import { Links } from "./Links";
import { Subtasks } from "./Subtasks";
import { TaskFields } from "./TaskFields";
import { TaskTitle } from "./TaskTitle";

const ACTIVITY_PAGE = 50;

function Section({ title, id, children }: { title: string; id?: string; children: React.ReactNode }) {
  return (
    <section id={id} className="space-y-2">
      <h3 className="text-[11px] tracking-widest text-muted-foreground uppercase">{title}</h3>
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
  const { ask, dialog } = useConfirm();
  const projectKey = taskKey.split("-")[0].toUpperCase();
  const client = useQueryClient();
  const { data: me } = useMe();
  const task = useQuery({ queryKey: qk.task(taskKey), queryFn: () => api<Task>(`/api/tasks/${taskKey}`) });
  const activity = useQuery({
    queryKey: qk.activity(taskKey),
    queryFn: () => api<ActivityItem[]>(`/api/tasks/${taskKey}/activity?limit=${ACTIVITY_PAGE}`),
  });
  // older pages, prepended as the user asks for them; the live first page keeps refreshing
  const [older, setOlder] = useState<{ items: ActivityItem[]; more: boolean }>({ items: [], more: true });
  const attachments = useQuery({ queryKey: qk.attachments(taskKey), queryFn: () => api<Attachment[]>(`/api/tasks/${taskKey}/attachments`) });
  const project = useProject(projectKey);
  const columns = useColumns(projectKey);
  const labels = useLabels(projectKey);
  const users = useUsers();
  const agents = useProjectAgents(projectKey);
  const sprints = useSprints(projectKey, project.data?.sprints_enabled ?? false);
  const all = useTasks(projectKey);
  const workflow = useWorkflow(taskKey);
  const mockups = useMockups(taskKey);
  const decisionCount = useRunRecords(taskKey).data?.decisions.length ?? 0;
  const [error, setError] = useState<string | null>(null);

  const userNames = useMemo(() => new Map(users.data?.map((u) => [u.id, u.name])), [users.data]);
  const activeUsers = useMemo(() => (users.data ?? []).filter((u) => u.status === "active"), [users.data]);
  const agentNames = useMemo(() => new Map(agents.data?.map((a) => [a.id, a.name])), [agents.data]);
  const columnNames = useMemo(() => new Map(columns.data?.map((c) => [c.id, c.name])), [columns.data]);

  if (task.error) return <p className="p-4 text-sm text-pink">{errorMessage(task.error)}</p>;
  const t = task.data;
  if (!t || !columns.data) return <p className="p-4 text-sm text-muted-foreground">Loading…</p>;

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
    <>
      <div className="flex h-full flex-col">
        <header className="flex items-start gap-2 border-b border-line p-4">
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <TypeIcon size={12} aria-hidden /> {t.key}
              <WaitingBadge projects={t.waiting_on} />
            </p>
            <TaskTitle
              value={t.title}
              disabled={disabled}
              onSave={(title) => void run(() => api(`/api/tasks/${t.key}`, { method: "PATCH", json: { title } }))}
            />
          </div>
          {!disabled && (
            <Hint label="Delete task">
              <button
                type="button"
                className="icon-btn hover:text-pink"
                aria-label="Delete task"
                onClick={async () => {
                  if (!(await ask({ tone: "danger", title: `Delete ${t.key}?`, text: t.type === "epic" ? "Its tasks stay, without an epic." : "Its subtasks are deleted too.", ok: "Delete" }))) return;
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
            </Hint>
          )}
          {headerExtra}
        </header>
        {error && <p role="alert" className="px-4 pt-2 text-sm text-pink">{error}</p>}
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] gap-6 overflow-y-auto p-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
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
            {(mockups.data?.length ?? 0) > 0 && (
              <Section id="mockups" title="Mockups">
                <MockupPanel taskKey={t.key} disabled={disabled} />
              </Section>
            )}
            {(["design", "plan"] as const).map(
              (kind) =>
                workflow.data?.documents.some((d) => d.kind === kind) && (
                  <Section key={kind} id={`document-${kind}`} title={kind === "design" ? "Design" : "Plan"}>
                    <DocumentView taskKey={t.key} kind={kind} disabled={disabled} />
                  </Section>
                ),
            )}
            {decisionCount > 0 && (
              <Section id="decisions" title={`Decisions (${decisionCount})`}>
                <Decisions taskKey={t.key} />
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
            <KbReferences taskKey={t.key} />
            <TaskQuestions taskKey={t.key} canAsk={!disabled} />
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
              <ActivityThread
                items={[...older.items, ...(activity.data ?? [])]}
                columnNames={columnNames}
                userNames={userNames}
                agentNames={agentNames}
                taskKey={taskKey}
                canAct={workflow.data?.can_act === true}
                readOnly={disabled}
                onAnswered={async () => {
                  // older pages are local state: reload the same range so an answered question does not stay open
                  const first = activity.data?.[0];
                  if (older.items.length === 0 || !first) return;
                  const params = new URLSearchParams({ limit: String(older.items.length), before: first.at, before_id: first.id });
                  const page = await api<ActivityItem[]>(`/api/tasks/${taskKey}/activity?${params}`);
                  setOlder((o) => ({ ...o, items: page }));
                }}
                hasMore={older.more && (older.items.length > 0 || (activity.data?.length ?? 0) >= ACTIVITY_PAGE)}
                onLoadEarlier={async () => {
                  const first = older.items[0] ?? activity.data?.[0];
                  if (!first) return;
                  const params = new URLSearchParams({ limit: String(ACTIVITY_PAGE), before: first.at, before_id: first.id });
                  const page = await api<ActivityItem[]>(`/api/tasks/${taskKey}/activity?${params}`);
                  setOlder({ items: [...page, ...older.items], more: page.length >= ACTIVITY_PAGE });
                }}
              />
              {!disabled && <CommentBox users={activeUsers} onSubmit={(body_md) => run(() => api(`/api/tasks/${t.key}/comments`, { method: "POST", json: { body_md } }))} />}
            </Section>
          </div>
          <aside className="space-y-4">
            <TaskFields
              task={t}
              columns={columns.data}
              users={users.data ?? []}
              agents={agents.data ?? []}
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
            {["story", "task", "bug"].includes(t.type) && (
              <WorkflowPanel
                taskKey={t.key}
                unassigned={t.assignee_agent_id == null}
                agent={t.assignee_agent_id ? agents.data?.find((a) => a.id === t.assignee_agent_id) : undefined}
                disabled={disabled}
              />
            )}
            <p className="text-[11px] text-muted-foreground">
              Reported by {t.reporter_id ? userNames.get(t.reporter_id) ?? "someone" : "someone"} ·{" "}
              {new Date(t.created_at).toLocaleDateString()}
            </p>
          </aside>
        </div>
      </div>
      {dialog}
    </>
  );
}
