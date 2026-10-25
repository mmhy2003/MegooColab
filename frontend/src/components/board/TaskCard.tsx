"use client";

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Bookmark, Bot, Bug, CheckSquare, ChevronDown, ChevronsDown, ChevronsUp, ChevronUp, Equal, Zap } from "lucide-react";

import { AgentStatusDot } from "@/components/agents/AgentStatusDot";
import { LabelChip } from "@/components/project/LabelEditor";
import { Avatar } from "@/components/ui/Avatar";
import { StageTrack } from "@/components/workflow/StageTrack";
import type { Priority, Task, TaskType } from "@/lib/types";
import { needsText } from "@/lib/workflow";

const PRIORITY_ICON: Record<Priority, { icon: typeof ChevronUp; className: string }> = {
  highest: { icon: ChevronsUp, className: "text-pink" },
  high: { icon: ChevronUp, className: "text-pink" },
  medium: { icon: Equal, className: "text-amber" },
  low: { icon: ChevronDown, className: "text-cyan-ink" },
  lowest: { icon: ChevronsDown, className: "text-cyan-ink" },
};

export const TYPE_ICON: Record<TaskType, typeof Bookmark> = {
  epic: Zap,
  story: Bookmark,
  task: CheckSquare,
  bug: Bug,
  subtask: CheckSquare,
};

const ENFORCEMENT_HELP = {
  unenforced: "MegooColab can't enforce the workflow rules here: the agent or a person works outside the runner.",
  partially_enforced: "The agent changed the repository when it shouldn't have, so some workflow rules were not enforced.",
  enforced: "",
} as const;

export function TaskCardView({
  task,
  assigneeName,
  dragging = false,
}: {
  task: Task;
  assigneeName?: string;
  dragging?: boolean;
}) {
  const P = PRIORITY_ICON[task.priority];
  const TypeIcon = TYPE_ICON[task.type];
  const wf = task.workflow;
  return (
    <div
      className={`card space-y-2 p-2.5 text-sm transition-shadow hover:border-cyan ${dragging ? "glow-box border-cyan" : ""}`}
    >
      <div className="flex items-center gap-1.5 text-[11px] text-muted">
        <TypeIcon size={12} aria-label={task.type} />
        <span>{task.key}</span>
        <span className="flex-1" />
        <P.icon size={14} className={P.className} aria-label={`Priority: ${task.priority}`} />
      </div>
      <p className="leading-snug break-words">{task.title}</p>
      {wf && (
        <div className="space-y-1">
          <StageTrack stage={wf.stage} status={wf.status} compact />
          <div className="flex flex-wrap items-center gap-1 text-[11px]">
            {wf.needs && wf.can_act && (
              <span
                className="rounded-full border-2 border-pink px-1.5 font-semibold tracking-wide text-pink"
                title={needsText(wf.needs)}
              >
                NEEDS YOU
              </span>
            )}
            {wf.stage === "build" && wf.current_step != null && wf.steps_total != null && (
              <span className="text-muted">
                {wf.current_step} of {wf.steps_total} steps
              </span>
            )}
            {wf.enforcement !== "enforced" && (
              <span
                className="rounded-full border border-line px-1.5 text-muted"
                title={ENFORCEMENT_HELP[wf.enforcement]}
              >
                {wf.enforcement === "unenforced" ? "unenforced" : "partially enforced"}
              </span>
            )}
          </div>
        </div>
      )}
      {task.labels.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {task.labels.map((l) => (
            <LabelChip key={l.id} label={l} />
          ))}
        </div>
      )}
      <div className="flex items-center gap-2 text-[11px] text-muted">
        {task.story_points != null && (
          <span aria-label={`${task.story_points} story points`} className="rounded-full border border-line px-1.5">
            {task.story_points}
          </span>
        )}
        {task.subtask_count > 0 && (
          <span aria-label={`${task.subtask_done_count} of ${task.subtask_count} subtasks done`}>
            {task.subtask_done_count}/{task.subtask_count}
          </span>
        )}
        <span className="flex-1" />
        {task.assignee_agent ? (
          <span className="inline-flex items-center gap-1" title={`Assigned to agent ${task.assignee_agent.name}`}>
            <span className="inline-grid h-5 w-5 place-items-center rounded-sm bg-cyan-ink text-on-accent" role="img" aria-label={`Agent ${task.assignee_agent.name}`}>
              <Bot size={12} aria-hidden />
            </span>
            <AgentStatusDot status={task.assignee_agent.status} />
          </span>
        ) : (
          assigneeName && (
          <span title={`Assigned to ${assigneeName}`}>
            <Avatar name={assigneeName} />
          </span>
          )
        )}
      </div>
    </div>
  );
}

export function SortableTaskCard({
  task,
  assigneeName,
  onOpen,
}: {
  task: Task;
  assigneeName?: string;
  onOpen: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: task.key,
    data: { columnId: task.column_id },
  });
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.4 : 1 }}
      {...attributes}
      {...listeners}
      aria-label={`${task.key} ${task.title}`}
      onClick={onOpen}
      onKeyDown={(e) => {
        listeners?.onKeyDown?.(e);
        if (e.key === "Enter" && !e.defaultPrevented) onOpen();
      }}
      className="cursor-grab list-none rounded focus-visible:outline-2 focus-visible:outline-cyan"
    >
      <TaskCardView task={task} assigneeName={assigneeName} />
    </li>
  );
}
