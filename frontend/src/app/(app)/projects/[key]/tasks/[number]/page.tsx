"use client";

import { useParams, useRouter } from "next/navigation";

import { NotFoundView } from "@/components/shell/NotFound";
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
  if (isNotFound(task.error)) return <NotFoundView />;
  return (
    <div className="card min-h-[70vh]">
      <TaskView
        taskKey={taskKey}
        onOpenTask={(k) => router.push(`/projects/${projectKey}/tasks/${k.split("-")[1]}`)}
        onDeleted={() => router.push(`/projects/${projectKey}/board`)}
      />
    </div>
  );
}
