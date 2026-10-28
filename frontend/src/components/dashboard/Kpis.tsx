import type { Numbers } from "@/lib/dashboard";

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

function Tile({
  label,
  value,
  of,
  small,
  alert = false,
  live = false,
}: {
  label: string;
  value: number;
  of?: number;
  small: string;
  alert?: boolean;
  live?: boolean;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      data-alert={alert}
      className={`card min-w-0 px-3 py-2.5 ${alert ? "border-pink" : ""}`}
    >
      <p className={`font-mono text-2xl leading-tight font-semibold ${alert ? "text-pink" : live ? "text-cyan-ink glow-cyan" : ""}`}>
        {value}
        {of !== undefined && <span className="ml-1 text-sm font-normal text-muted-foreground">/ {of}</span>}
      </p>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-[11px] text-muted-foreground">{small}</p>
    </div>
  );
}

function doneTrend(now: number, before: number): string {
  if (now === before) return "same as the 7 days before";
  return `${now > before ? "▲" : "▼"} ${Math.abs(now - before)} on the 7 days before`;
}

/** The headline numbers across the top of the dashboard. */
export function Kpis({ numbers: n }: { numbers: Numbers }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(8.5rem,1fr))] gap-2.5">
      <Tile label="Need you" value={n.need_you} small={`${n.need_you_over_day} over a day old`} alert={n.need_you > 0} />
      <Tile label="Agents working / online" value={n.agents_working} of={n.agents_online} small={plural(n.runs_queued, "run") + " queued"} live />
      <Tile label="Workflows in progress" value={n.workflows_in_progress} small={`across ${plural(n.workflow_projects, "project")}`} />
      <Tile label="Open tasks" value={n.open_tasks} small={`${n.open_in_progress} in progress`} />
      <Tile label="Done, last 7 days" value={n.done_7d} small={doneTrend(n.done_7d, n.done_prev_7d)} />
      <Tile label="Overdue" value={n.overdue} small={`${n.overdue_mine} assigned to you`} alert={n.overdue > 0} />
      <Tile
        label="Failed runs, 24 h"
        value={n.failed_24h}
        small={n.success_rate_24h === null || n.success_rate_24h === undefined ? "no runs finished" : `${Math.round(n.success_rate_24h * 100)}% succeeded`}
      />
    </div>
  );
}
