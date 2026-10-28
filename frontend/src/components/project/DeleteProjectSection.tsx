"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import type { Project, User } from "@/lib/types";

const DANGER = "border-pink bg-pink text-white glow-box-pink hover:bg-pink dark:bg-pink dark:text-white";

/** Admins only: deleting a project removes everything tied to it and cannot be undone, so the key is typed. */
export function DeleteProjectSection({ project, user }: { project: Project; user: User }) {
  const client = useQueryClient();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (user.role !== "admin") return null;
  const close = () => {
    setOpen(false);
    setTyped("");
    setError(null);
  };
  return (
    <section aria-label="Delete project" className="card max-w-xl space-y-2 border-pink/60 p-4">
      <h2 className="text-xs tracking-wider text-pink uppercase">Delete project</h2>
      <p className="text-sm text-muted-foreground">
        Removes this project and everything in it. This can&apos;t be undone.
      </p>
      <Button variant="ghost" className="text-pink" onClick={() => setOpen(true)}>
        Delete project
      </Button>
      {/* mounted only while open, as Dialog expects */}
      {open && (
        <Dialog open onClose={close} title={`Delete ${project.key}?`}>
          <div className="space-y-3 text-sm">
            <p>
              This deletes {project.name} with its tasks, sprints, board, labels, repositories, its Knowledge Base
              space, what Memory learned only from it, questions sent to it, and attachments.
            </p>
            <Input
              label={`Type ${project.key} to confirm`}
              value={typed}
              autoComplete="off"
              onChange={(e) => setTyped(e.target.value)}
            />
            {error && (
              <p role="alert" className="text-pink">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={close}>
                Cancel
              </Button>
              <Button
                className={DANGER}
                disabled={typed !== project.key || busy}
                onClick={async () => {
                  setBusy(true);
                  setError(null);
                  try {
                    await api(`/api/projects/${project.key}`, {
                      method: "DELETE",
                    });
                    void client.invalidateQueries({ queryKey: qk.projects() });
                    router.push("/projects");
                  } catch (err) {
                    setError(errorMessage(err));
                    setBusy(false);
                  }
                }}
              >
                Delete {project.key} for good
              </Button>
            </div>
          </div>
        </Dialog>
      )}
    </section>
  );
}
