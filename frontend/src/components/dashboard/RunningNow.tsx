"use client";

import { Activity } from "lucide-react";
import Link from "next/link";
import { Fragment } from "react";

import { Dot, Empty, Widget } from "@/components/dashboard/Widget";
import { RunLink } from "@/components/runs/RunLink";
import { type Queued, type RunningItem, shortDuration } from "@/lib/dashboard";
import { STAGE_LABEL, runStatus, useNow } from "@/lib/runs";

function QueuedLine({ queued }: { queued: Queued }) {
  const more = queued.total - queued.items.length;
  return (
    <>
      Queued:{" "}
      {queued.items.map((q, i) => (
        <Fragment key={i}>
          {i > 0 && " · "}
          {q.task_key && q.link ? (
            <Link href={q.link} className="text-cyan-ink no-underline hover:underline">{q.task_key}</Link>
          ) : (
            q.task_key ?? "a question"
          )}
          {q.task_key && q.stage ? ` ${STAGE_LABEL[q.stage]}` : ""}
        </Fragment>
      ))}
      {more > 0 ? ` and ${more} more` : ""}
    </>
  );
}

/** Agent runs at work now, with their time ticking in the browser, and what waits in the queue. */
export function RunningNow({ running, queued, isAdmin }: { running: RunningItem[]; queued: Queued; isAdmin: boolean }) {
  const now = useNow();
  return (
    <Widget title="Running now" icon={Activity} more={{ href: isAdmin ? "/admin/agents" : "/settings/agents", label: "All runs" }}>
      {running.length === 0 && queued.total === 0 ? (
        <Empty>No agent is running.</Empty>
      ) : (
        <ul className="divide-y divide-line">
          {running.length === 0 && (
            <li className="py-1.5">
              <Empty>No agent is running.</Empty>
            </li>
          )}
          {running.map((run) => (
            <li key={run.run_id} className="space-y-0.5 py-1.5 text-sm">
              <div className="flex min-w-0 items-center gap-1.5">
                <Dot state="busy" />
                <RunLink run={run} />
                {run.kind === "task" && run.title && <span className="min-w-0 truncate">{run.title}</span>}
              </div>
              <div className="flex min-w-0 items-center gap-2 pl-3.5 text-xs text-muted-foreground">
                <span className="min-w-0 truncate font-semibold text-foreground">{run.agent_name}</span>
                <span className="shrink-0 rounded-full border border-line px-1.5">{runStatus(run)}</span>
                {run.started_at && <span className="ml-auto shrink-0">{shortDuration(now - Date.parse(run.started_at))}</span>}
              </div>
            </li>
          ))}
          {queued.total > 0 && (
            <li className="flex min-w-0 items-center gap-2 py-1.5 text-sm text-muted-foreground">
              <Dot state="offline" />
              <span className="min-w-0 flex-1 truncate"><QueuedLine queued={queued} /></span>
            </li>
          )}
        </ul>
      )}
    </Widget>
  );
}
