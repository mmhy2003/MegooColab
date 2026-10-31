"use client";

import { useParams, useRouter } from "next/navigation";
import { useRef } from "react";

import { NotFoundView } from "@/components/shell/NotFound";
import { useFillWindow } from "@/components/task/fillWindow";
import { TaskView } from "@/components/task/TaskView";
import { isNotFound } from "@/lib/errors";
import { useTask } from "@/lib/project";

export default function TaskPage() {
  const { key, number } = useParams<{ key: string; number: string }>();
  const router = useRouter();
  const projectKey = key.toUpperCase();
  const taskKey = `${projectKey}-${number}`;
  // the same query TaskView reads: a task that is gone shows the not-found page instead of its card
  const task = useTask(taskKey);
  const card = useRef<HTMLDivElement | null>(null);
  useFillWindow(card);
  if (isNotFound(task.error)) return <NotFoundView />;
  return (
    // down to the window's bottom, so the task scrolls inside the card as it does in the drawer and the corner
    // buttons (JumpButtons) stay in view
    <div ref={card} className="card">
      <TaskView
        taskKey={taskKey}
        onOpenTask={(k) => router.push(`/projects/${projectKey}/tasks/${k.split("-")[1]}`)}
        onDeleted={() => router.push(`/projects/${projectKey}/board`)}
      />
    </div>
  );
}
