"use client";

import { useId, useState } from "react";

import { RunLink } from "@/components/runs/RunLink";
import { type RunningItem, shortDuration } from "@/lib/dashboard";
import { runStatus, useNow } from "@/lib/runs";

/** What an agent is working on, newest first. `collapsed`: the newest only, the rest behind "+N more" (the
 *  Admin table keeps its rows one height). `titles`: a task's title after its key. No run: a dash. */
export function WorkingOn({ runs, collapsed = false, titles = false }: { runs: RunningItem[]; collapsed?: boolean; titles?: boolean }) {
  const [open, setOpen] = useState(false);
  const now = useNow();
  const id = useId();
  if (runs.length === 0) return <span className="text-muted-foreground">—</span>;
  const shown = collapsed && !open ? runs.slice(0, 1) : runs;
  return (
    <div className="min-w-0 space-y-1">
      <ul id={id} aria-label="Working on" className="space-y-1">
        {shown.map((run) => (
          <li key={run.run_id} className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-sm">
            <RunLink run={run} />
            {titles && run.kind === "task" && run.title && <span className="min-w-0 truncate">{run.title}</span>}
            <span className="shrink-0 text-xs text-muted-foreground">{runStatus(run)}</span>
            {run.started_at && (
              <span className="shrink-0 text-xs text-muted-foreground">{shortDuration(now - Date.parse(run.started_at))}</span>
            )}
          </li>
        ))}
      </ul>
      {collapsed && runs.length > 1 && (
        <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}
          className="text-xs text-cyan-ink hover:underline">
          {open ? "Show less" : `+${runs.length - 1} more`}
        </button>
      )}
    </div>
  );
}
