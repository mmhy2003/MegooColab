"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";

import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Hint } from "@/components/ui/Hint";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Sprint } from "@/lib/types";

/** Deletes a sprint after saying where its tasks go (back to the backlog) and, once it has started, what is lost. */
export function DeleteSprintButton({ sprint, taskCount }: { sprint: Sprint; taskCount: number }) {
  const client = useQueryClient();
  const { ask, dialog } = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const tasks = `${taskCount} ${taskCount === 1 ? "task goes" : "tasks go"} back to the backlog.`;
  return (
    <>
      <Hint label="Delete sprint">
        <button
          type="button"
          className="icon-btn hover:text-pink"
          aria-label={`Delete sprint ${sprint.name}`}
          onClick={async () => {
            const history = sprint.state === "planned" ? "" : " Its burndown and velocity history is lost.";
            if (
              !(await ask({
                tone: "danger",
                title: `Delete ${sprint.name}?`,
                text: tasks + history,
                ok: "Delete",
              }))
            )
              return;
            setError(null);
            try {
              await api(`/api/sprints/${sprint.id}`, { method: "DELETE" });
              for (const queryKey of [["sprints"], ["tasks"], ["burndown"], ["velocity"]]) {
                void client.invalidateQueries({ queryKey });
              }
            } catch (err) {
              setError(errorMessage(err));
            }
          }}
        >
          <Trash2 size={16} aria-hidden />
        </button>
      </Hint>
      {error && (
        <span role="alert" className="text-xs text-pink">
          {error}
        </span>
      )}
      {dialog}
    </>
  );
}
