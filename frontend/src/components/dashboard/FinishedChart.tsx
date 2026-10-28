import { BarChart3 } from "lucide-react";

import { Empty, Widget } from "@/components/dashboard/Widget";
import type { DayFinished } from "@/lib/dashboard";

function dayLabel(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Tasks finished per day over the last 14 days, stacked: by agents (cyan) and by people (violet). Plain elements, no
 * chart library. */
export function FinishedChart({ days }: { days: DayFinished[] }) {
  const agents = days.reduce((n, d) => n + d.agents, 0);
  const people = days.reduce((n, d) => n + d.people, 0);
  const max = Math.max(1, ...days.map((d) => d.agents + d.people));
  const middle = Math.floor(days.length / 2);
  return (
    <Widget title="Tasks finished · last 14 days" icon={BarChart3}>
      {agents + people === 0 ? (
        <Empty>No tasks finished in the last 14 days.</Empty>
      ) : (
        <>
          <div
            role="img"
            aria-label={`Tasks finished in the last 14 days: ${agents} by agents, ${people} by people`}
            className="flex h-28 items-end gap-1 pt-1.5"
          >
            {days.map((d) => (
              <div key={d.day} data-day className="flex h-full flex-1 flex-col-reverse gap-px" title={`${dayLabel(d.day)}: ${d.agents} by agents, ${d.people} by people`}>
                <b className="block rounded-t-sm bg-cyan" style={{ height: `${(d.agents / max) * 100}%` }} />
                <b className="block rounded-t-sm bg-violet" style={{ height: `${(d.people / max) * 100}%` }} />
              </div>
            ))}
          </div>
          {days.length > 0 && (
            <p aria-hidden className="mt-1 flex justify-between text-[10px] text-muted-foreground">
              <span>{dayLabel(days[0].day)}</span>
              <span>{dayLabel(days[middle].day)}</span>
              <span>{dayLabel(days[days.length - 1].day)}</span>
            </p>
          )}
          <p className="mt-1.5 flex flex-wrap gap-x-3 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <i className="inline-block size-2.5 rounded-sm bg-cyan" />
              by agents · {agents}
            </span>
            <span className="inline-flex items-center gap-1">
              <i className="inline-block size-2.5 rounded-sm bg-violet" />
              by people · {people}
            </span>
          </p>
        </>
      )}
    </Widget>
  );
}
