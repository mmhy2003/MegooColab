"use client";

import { History } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Dot, Empty, Widget } from "@/components/dashboard/Widget";
import { describeEvent } from "@/components/task/ActivityThread";
import { type ActivityRow, minuteAge, taskLink } from "@/lib/dashboard";

/** The latest task events in scope, worded as a task's own activity list words them. */
export function RecentActivity({ rows }: { rows: ActivityRow[] }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);
  return (
    <Widget title="Recent activity" icon={History}>
      {rows.length === 0 ? (
        <Empty>No activity yet.</Empty>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map((row) => {
            // the server names every id the event mentions; describeEvent looks each kind up in its own map
            const names = new Map(Object.entries(row.names));
            const text = describeEvent(row.kind, row.data, { columnNames: names, userNames: names, agentNames: names }, !!row.actor_name);
            return (
              <li key={row.id} className="flex min-w-0 items-center gap-2 py-1.5 text-sm">
                <Dot state="online" />
                <span className="min-w-0 flex-1 truncate">
                  <b className="font-semibold">{row.actor_name ?? "MegooColab"}</b> {text}
                  {" · "}
                  <Link href={taskLink(row.task_key)} className="font-mono text-xs text-cyan-ink no-underline hover:underline">
                    {row.task_key}
                  </Link>
                </span>
                <span className="shrink-0 text-xs text-muted-foreground">{minuteAge(now - Date.parse(row.at))}</span>
              </li>
            );
          })}
        </ul>
      )}
    </Widget>
  );
}
