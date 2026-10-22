"use client";

import { useParams, useRouter } from "next/navigation";

import { TaskView } from "@/components/task/TaskView";

export default function TaskPage() {
  const { key, number } = useParams<{ key: string; number: string }>();
  const router = useRouter();
  const projectKey = key.toUpperCase();
  return (
    <div className="card min-h-[70vh]">
      <TaskView
        taskKey={`${projectKey}-${number}`}
        onOpenTask={(k) => router.push(`/projects/${projectKey}/tasks/${k.split("-")[1]}`)}
        onDeleted={() => router.push(`/projects/${projectKey}/board`)}
      />
    </div>
  );
}
