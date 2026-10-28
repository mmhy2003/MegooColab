import { UserRoundCheck } from "lucide-react";
import Link from "next/link";

import { Chip, Empty, type Tone, Widget } from "@/components/dashboard/Widget";
import type { MyTask } from "@/lib/dashboard";

const DUE: Record<MyTask["due"], { label: string; tone: Tone }> = {
  overdue: { label: "Overdue", tone: "pink" },
  today: { label: "Today", tone: "amber" },
  week: { label: "This week", tone: "muted" },
};

function dueText(task: MyTask): string {
  if (task.due === "today") return "due today";
  const date = new Date(`${task.due_date}T00:00:00`);
  return `due ${date.toLocaleDateString(undefined, task.due === "week" ? { weekday: "short" } : { day: "numeric", month: "short" })}`;
}

/** The viewer's own open tasks that are overdue or due by Sunday, whatever the scope. */
export function MyTasks({ items }: { items: MyTask[] }) {
  return (
    <Widget title="My tasks" icon={UserRoundCheck}>
      {items.length === 0 ? (
        <Empty>No tasks due this week.</Empty>
      ) : (
        <ul className="divide-y divide-line">
          {items.map((task) => (
            <li key={task.key} className="flex min-w-0 items-center gap-2 py-1.5 text-sm">
              <Chip tone={DUE[task.due].tone}>{DUE[task.due].label}</Chip>
              <Link href={task.link} className="shrink-0 font-mono text-xs text-cyan-ink no-underline hover:underline">
                {task.key}
              </Link>
              <span className="min-w-0 flex-1 truncate">{task.title}</span>
              <span className="shrink-0 text-xs text-muted-foreground">{dueText(task)}</span>
            </li>
          ))}
        </ul>
      )}
    </Widget>
  );
}
