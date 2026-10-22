"use client";

import { Dialog } from "@/components/ui/Dialog";

// Minimal drawer; the full task view arrives in Task 21.
export function TaskDrawer({
  taskKey,
  onClose,
}: {
  taskKey: string;
  onClose: () => void;
  onOpenTask?: (key: string) => void;
}) {
  return (
    <Dialog open title={taskKey} onClose={onClose}>
      <p className="text-sm text-muted">Task details coming soon.</p>
    </Dialog>
  );
}
