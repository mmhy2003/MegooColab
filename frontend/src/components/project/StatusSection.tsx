"use client";

import { useState } from "react";

import { useConfirm } from "@/components/ui/ConfirmDialog";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { type ProjectStatus, STATUS_LABEL, useSetProjectStatus } from "@/lib/projectStatus";
import type { Project } from "@/lib/types";

const ORDER: ProjectStatus[] = ["active", "finished", "archived"];
const VERB: Record<ProjectStatus, string> = { active: "Reopen", finished: "Finish", archived: "Archive" };

/** Active, Finished or Archived. Closing a project with work in progress says first how much will be paused. */
export function StatusSection({ project, canChange }: { project: Project; canChange: boolean }) {
  const setStatus = useSetProjectStatus(project.key);
  const { ask, dialog } = useConfirm();
  const [error, setError] = useState<string | null>(null);

  const choose = async (status: ProjectStatus) => {
    setError(null);
    try {
      if (project.status === "active" && status !== "active") {
        const { count } = await api<{ count: number }>(`/api/projects/${project.key}/workflows-in-progress`);
        if (count > 0) {
          const ok = await ask({
            tone: "warn",
            title: `${VERB[status]} ${project.key}?`,
            text: `${count} ${count === 1 ? "workflow" : "workflows"} in progress will be paused.`,
            ok: VERB[status],
          });
          if (!ok) return;
        }
      }
      await setStatus.mutateAsync(status);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <section aria-label="Status" className="card max-w-xl space-y-2 p-4">
      <h2 className="text-xs tracking-wider text-muted-foreground uppercase">Status</h2>
      {canChange ? (
        <div role="group" aria-label="Project status" className="inline-flex overflow-hidden rounded border border-line">
          {ORDER.map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={project.status === s}
              disabled={setStatus.isPending}
              onClick={() => project.status !== s && void choose(s)}
              className={`px-3 py-1 text-sm ${project.status === s ? "bg-surface-2 text-cyan-ink" : "text-muted-foreground hover:text-fg"}`}
            >
              {STATUS_LABEL[s]}
            </button>
          ))}
        </div>
      ) : (
        <p className="text-sm">{STATUS_LABEL[project.status]}</p>
      )}
      <p className="text-xs text-muted-foreground">
        Finished and archived projects are read-only and agents can&apos;t start work in them. Archived projects are
        also hidden from lists, the dashboard and search. Their Knowledge Base and Memory are kept.
      </p>
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      {dialog}
    </section>
  );
}
