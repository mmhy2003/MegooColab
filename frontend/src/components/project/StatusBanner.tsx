"use client";

import { Lock } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { useSetProjectStatus } from "@/lib/projectStatus";
import type { Project } from "@/lib/types";

const TEXT = {
  finished: { text: "This project is finished. It is read-only.", action: "Reopen" },
  archived: { text: "This project is archived. It is read-only and hidden from lists.", action: "Restore" },
} as const;

/** On every page of a closed project; Reopen or Restore for those who may change its status. */
export function StatusBanner({ project, canChange }: { project: Project; canChange: boolean }) {
  const setStatus = useSetProjectStatus(project.key);
  if (project.status === "active") return null;
  const { text, action } = TEXT[project.status];
  return (
    <div role="status" className="flex flex-wrap items-center gap-2 rounded border border-amber/60 bg-amber/10 px-3 py-2 text-sm">
      <Lock size={14} aria-hidden className="shrink-0 text-amber" />
      <span className="min-w-0 flex-1">{text}</span>
      {canChange && (
        <Button variant="ghost" disabled={setStatus.isPending} onClick={() => setStatus.mutate("active")}>
          {action}
        </Button>
      )}
    </div>
  );
}
