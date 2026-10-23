"use client";

import { Eye, EyeOff } from "lucide-react";

import type { Column, Label, Priority, ProjectAgent, Sprint, Task, TaskType, User } from "@/lib/types";

const PRIORITIES: Priority[] = ["highest", "high", "medium", "low", "lowest"];
const TYPES: TaskType[] = ["epic", "story", "task", "bug", "subtask"];
const AGENT_DENIED = "Only the owner, project managers and admins can assign this agent";
const FIELD = "w-full rounded border border-line bg-surface-2 px-2 py-1 text-sm disabled:opacity-60";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[6.5rem_1fr] items-center gap-2">
      <span className="text-[11px] tracking-wider text-muted uppercase">{label}</span>
      {children}
    </div>
  );
}

export function TaskFields({
  task,
  columns,
  users,
  agents = [],
  labels,
  parents,
  sprints,
  meId,
  disabled,
  onPatch,
  onMove,
  onSprint,
  onWatch,
}: {
  task: Task;
  columns: Column[];
  users: User[];
  agents?: ProjectAgent[];
  labels: Label[];
  parents: Task[];
  sprints: Sprint[] | undefined;
  meId: string | undefined;
  disabled: boolean;
  onPatch: (patch: Record<string, unknown>) => void;
  onMove: (columnId: string) => void;
  onSprint: (sprintId: string | null) => void;
  onWatch: (watch: boolean) => void;
}) {
  const watching = meId ? task.watcher_ids.includes(meId) : false;
  const selectedLabels = new Set(task.labels.map((l) => l.id));
  return (
    <div className="space-y-2.5">
      <Row label="Status">
        <select aria-label="Status" className={FIELD} disabled={disabled} value={task.column_id} onChange={(e) => onMove(e.target.value)}>
          {columns.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </Row>
      <Row label="Type">
        <select aria-label="Type" className={FIELD} disabled={disabled} value={task.type} onChange={(e) => onPatch({ type: e.target.value })}>
          {TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </Row>
      <Row label="Assignee">
        <select
          aria-label="Assignee"
          className={FIELD}
          disabled={disabled}
          value={task.assignee_agent_id ? `agent:${task.assignee_agent_id}` : task.assignee_user_id ? `user:${task.assignee_user_id}` : ""}
          onChange={(e) => {
            const [kind, id] = e.target.value.split(":");
            onPatch(kind === "agent" ? { assignee_agent_id: id } : { assignee_user_id: id || null });
          }}
        >
          <option value="">Unassigned</option>
          <optgroup label="People">
            {users.filter((u) => u.status !== "deactivated" || u.id === task.assignee_user_id).map((u) => (
              <option key={u.id} value={`user:${u.id}`}>{u.name}</option>
            ))}
          </optgroup>
          {(agents.length > 0 || task.assignee_agent) && (
            <optgroup label="Agents">
              {agents.map((a) => (
                <option key={a.id} value={`agent:${a.id}`} disabled={!a.can_use} title={a.can_use ? undefined : AGENT_DENIED}>
                  {a.name}
                </option>
              ))}
              {task.assignee_agent && !agents.some((a) => a.id === task.assignee_agent_id) && (
                <option value={`agent:${task.assignee_agent.id}`} disabled>{task.assignee_agent.name}</option>
              )}
            </optgroup>
          )}
        </select>
      </Row>
      <Row label="Priority">
        <select aria-label="Priority" className={FIELD} disabled={disabled} value={task.priority} onChange={(e) => onPatch({ priority: e.target.value })}>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </Row>
      <Row label="Points">
        <input
          aria-label="Story points"
          type="number"
          min={0}
          className={FIELD}
          disabled={disabled}
          defaultValue={task.story_points ?? ""}
          key={`pts-${task.story_points}`}
          onBlur={(e) => {
            const v = e.target.value === "" ? null : Number(e.target.value);
            if (v !== task.story_points) onPatch({ story_points: v });
          }}
        />
      </Row>
      <Row label="Due">
        <input aria-label="Due date" type="date" className={FIELD} disabled={disabled} value={task.due_date ?? ""} onChange={(e) => onPatch({ due_date: e.target.value || null })} />
      </Row>
      {task.type !== "epic" && (
        <Row label={task.type === "subtask" ? "Parent" : "Epic"}>
          <select aria-label={task.type === "subtask" ? "Parent" : "Epic"} className={FIELD} disabled={disabled} value={task.parent_id ?? ""} onChange={(e) => onPatch({ parent_id: e.target.value || null })}>
            {task.type !== "subtask" && <option value="">None</option>}
            {parents.map((p) => (
              <option key={p.id} value={p.id}>{p.key} {p.title}</option>
            ))}
          </select>
        </Row>
      )}
      {sprints && ["story", "task", "bug"].includes(task.type) && (
        <Row label="Sprint">
          <select aria-label="Sprint" className={FIELD} disabled={disabled} value={task.sprint_id ?? ""} onChange={(e) => onSprint(e.target.value || null)}>
            <option value="">Backlog</option>
            {sprints.filter((s) => s.state !== "completed" || s.id === task.sprint_id).map((s) => (
              <option key={s.id} value={s.id}>{s.name}{s.state === "active" ? " (active)" : ""}</option>
            ))}
          </select>
        </Row>
      )}
      <Row label="Labels">
        <div className="flex flex-wrap gap-1.5">
          {labels.map((l) => (
            <label key={l.id} className="flex items-center gap-1 text-xs">
              <input
                type="checkbox"
                disabled={disabled}
                checked={selectedLabels.has(l.id)}
                onChange={(e) => {
                  const next = new Set(selectedLabels);
                  if (e.target.checked) next.add(l.id);
                  else next.delete(l.id);
                  onPatch({ label_ids: [...next] });
                }}
              />
              <span className="h-2 w-2 rounded-full" style={{ background: l.color }} aria-hidden />
              {l.name}
            </label>
          ))}
          {labels.length === 0 && <span className="text-xs text-muted">No labels in this project.</span>}
        </div>
      </Row>
      <button type="button" className="flex items-center gap-1.5 text-xs text-cyan-ink" onClick={() => onWatch(!watching)}>
        {watching ? <EyeOff size={14} aria-hidden /> : <Eye size={14} aria-hidden />}
        {watching ? "Stop watching" : "Watch"} ({task.watcher_ids.length})
      </button>
    </div>
  );
}
