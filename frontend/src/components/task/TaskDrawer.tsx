"use client";

import { Maximize2, X } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { TaskView } from "./TaskView";

export function TaskDrawer({
  taskKey,
  onClose,
  onOpenTask,
}: {
  taskKey: string;
  onClose: () => void;
  onOpenTask: (key: string) => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const [projectKey, number] = taskKey.split("-");
  return (
    <div className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label={taskKey}>
      {/* No close on an outside click: the drawer holds a comment box and editors, so ✕ or Escape closes it */}
      <div data-backdrop aria-hidden className="absolute inset-0 bg-black/40 backdrop-blur-sm" />
      <div className="card absolute inset-y-0 right-0 w-full max-w-4xl rounded-none border-y-0 border-r-0">
        <TaskView
          taskKey={taskKey}
          onOpenTask={onOpenTask}
          onDeleted={onClose}
          headerExtra={
            <>
              <Link href={`/projects/${projectKey}/tasks/${number}`} className="icon-btn" aria-label="Open full page">
                <Maximize2 size={16} aria-hidden />
              </Link>
              <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
                <X size={16} aria-hidden />
              </button>
            </>
          }
        />
      </div>
    </div>
  );
}
