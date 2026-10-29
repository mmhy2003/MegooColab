"use client";

import { Activity } from "lucide-react";
import Link from "next/link";
import { Fragment, useEffect, useState } from "react";

import { Dot, Empty, Widget } from "@/components/dashboard/Widget";
import { type Queued, type RunningItem, shortDuration } from "@/lib/dashboard";
import { STAGES } from "@/lib/workflow";

/** A run in the Done stage is the finish run. */
export const STAGE_LABEL: Record<string, string> = {
  ...Object.fromEntries(STAGES.map((s) => [s.id, s.label])),
  done: "Finishing",
};

/** Where the run is: the stage, with the review round past the first. */
function where(run: RunningItem): string {
  const stage = run.stage ? STAGE_LABEL[run.stage] : "";
  if (run.stage === "review" && run.review_round && run.review_round > 1) return `${stage}, round ${run.review_round}`;
  return stage;
}

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
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
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
            <li key={run.run_id} className="flex min-w-0 items-center gap-2 py-1.5 text-sm">
              <Dot state="busy" />
              <span className="min-w-0 flex-1 truncate">
                <b className="font-semibold">{run.agent_name}</b>
                {" · "}
                {run.task_key ? (
                  <>
                    <Link href={run.link} className="font-mono text-xs text-cyan-ink no-underline hover:underline">
                      {run.task_key}
                    </Link>{" "}
                    {where(run)}
                    {run.stage === "build" && run.step && run.steps_total && (
                      <>
                        {" · "}
                        <span className="text-muted-foreground">{`Step ${run.step} of ${run.steps_total}`}</span>
                      </>
                    )}
                  </>
                ) : (
                  <Link href={run.link} className="text-cyan-ink no-underline hover:underline">
                    {run.question_from ? `Answering a question from ${run.question_from}` : "Answering a question"}
                  </Link>
                )}
              </span>
              {run.started_at && (
                <span className="shrink-0 text-xs text-muted-foreground">{shortDuration(now - Date.parse(run.started_at))}</span>
              )}
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
