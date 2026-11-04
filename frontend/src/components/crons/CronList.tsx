"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { CronEditor } from "@/components/crons/CronEditor";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { cronKeys, cronsPath, runOutcome, useCrons, type Cron } from "@/lib/crons";
import { errorMessage } from "@/lib/errors";

const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString() : "—");

/** A project's crons: what each does, when it runs (in words and as written), how its last run went. */
export function CronList({ projectKey, canManage }: { projectKey: string; canManage: boolean }) {
  const client = useQueryClient();
  const crons = useCrons(projectKey);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const act = async (cron: Cron, action: "run-now" | "pause" | "resume") => {
    setError(null);
    try {
      await api(`${cronsPath(projectKey)}/${cron.id}/${action}`, { method: "POST" });
      await client.invalidateQueries({ queryKey: cronKeys.all });
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">
          Jobs one of the project&apos;s agents runs on a schedule, each time once.
        </p>
        {canManage && <Button onClick={() => setEditing(true)}>New cron</Button>}
      </div>
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      {crons.data?.length === 0 && <p className="text-sm text-muted-foreground">No crons yet.</p>}
      <ul className="divide-y divide-line rounded border border-line">
        {(crons.data ?? []).map((c) => (
          <li key={c.id} className="grid min-w-0 gap-x-4 gap-y-1 p-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1.2fr)_minmax(0,1.4fr)_auto]">
            <div className="min-w-0">
              <Link href={`/projects/${projectKey}/crons/${c.id}`} className="font-semibold">{c.name}</Link>
              <p className="truncate text-xs text-muted-foreground">{c.prompt.split("\n")[0]}</p>
            </div>
            <div className="min-w-0 text-sm">
              <span>{c.description}</span>
              <span className="block font-mono text-xs text-muted-foreground">{c.schedule}</span>
            </div>
            <div className="min-w-0 text-sm">
              <span className="block text-xs text-muted-foreground">
                Next: {c.paused ? "paused" : when(c.next_run_at)} · {c.agent?.name ?? "any free agent"}
              </span>
              {c.last_run && <span className="block">{runOutcome(c.last_run)}</span>}
            </div>
            {canManage && (
              <div className="flex flex-wrap items-start gap-2">
                <Button variant="ghost" onClick={() => void act(c, "run-now")}>Run now</Button>
                {c.paused ? (
                  <Button variant="ghost" onClick={() => void act(c, "resume")}>Resume</Button>
                ) : (
                  <Button variant="ghost" onClick={() => void act(c, "pause")}>Pause</Button>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
      {editing && <CronEditor projectKey={projectKey} onClose={() => setEditing(false)} />}
    </section>
  );
}
