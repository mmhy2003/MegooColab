"use client";

import { ChevronDown, ChevronUp } from "lucide-react";

import type { Column, ProjectAgent, Sprint, Task, User } from "@/lib/types";

const CHIP = "rounded-full border border-line px-2 py-0.5 text-xs text-fg";

/**
 * In one column (a phone, a narrow window), the task's details fold to one line of what matters most: its status,
 * who has it, its priority, and its sprint and due date when set. "Show all" opens the full list in place.
 */
export function DetailsSummary({
  task,
  columns,
  users,
  agents,
  sprints,
  open,
  onToggle,
  controls,
}: {
  task: Task;
  columns: Column[];
  users: User[];
  agents: ProjectAgent[];
  sprints: Sprint[] | undefined;
  open: boolean;
  onToggle: () => void;
  /** the id of the full list this opens */
  controls: string;
}) {
  const status = columns.find((c) => c.id === task.column_id)?.name;
  const assignee = task.assignee_agent_id
    ? task.assignee_agent?.name ?? agents.find((a) => a.id === task.assignee_agent_id)?.name ?? "An agent"
    : task.assignee_user_id
      ? users.find((u) => u.id === task.assignee_user_id)?.name ?? "Someone"
      : "Unassigned";
  const sprint = task.sprint_id ? sprints?.find((s) => s.id === task.sprint_id)?.name : undefined;
  const due = task.due_date ? new Date(`${task.due_date}T00:00:00`).toLocaleDateString() : undefined;
  return (
    <div data-details-summary className="space-y-2 lg:hidden">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[11px] tracking-widest text-muted-foreground uppercase">Details</h3>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={controls}
          aria-label={open ? "Hide details" : "Show all details"}
          onClick={onToggle}
          className="flex min-h-8 items-center gap-1 text-xs text-cyan-ink hover:text-fg"
        >
          {open ? "Hide" : "Show all"}
          {open ? <ChevronUp size={14} aria-hidden /> : <ChevronDown size={14} aria-hidden />}
        </button>
      </div>
      {!open && (
        <ul className="flex flex-wrap gap-1.5">
          {status && <li className={CHIP}>{status}</li>}
          <li className={CHIP}>{assignee}</li>
          <li className={CHIP}>{task.priority}</li>
          {sprint && <li className={CHIP}>{sprint}</li>}
          {due && <li className={CHIP}>Due {due}</li>}
        </ul>
      )}
    </div>
  );
}
