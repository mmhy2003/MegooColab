import { GitBranch } from "lucide-react";

import { STAGE_LABEL } from "@/components/dashboard/RunningNow";
import { Empty, Widget } from "@/components/dashboard/Widget";
import type { Stages } from "@/lib/dashboard";

const SEGMENTS = [
  { key: "running", label: "agent working", className: "bg-cyan" },
  { key: "waiting", label: "waiting for a person", className: "bg-amber" },
  { key: "paused", label: "paused or manual", className: "bg-muted-foreground/50" },
] as const;

function Row({ label, total, children }: { label: string; total: number; children: React.ReactNode }) {
  return (
    <div role="group" aria-label={label} className="grid grid-cols-[5.5rem_minmax(0,1fr)_2.5rem] items-center gap-2 py-1 text-sm">
      <span className="truncate">{label}</span>
      <span className="flex h-2.5 overflow-hidden rounded-sm bg-surface-2">{children}</span>
      <span className="text-right font-mono text-xs text-muted-foreground">{total}</span>
    </div>
  );
}

/** Workflows started and not finished, per stage, split by who they wait on; bars are scaled to the largest stage.
 * Done (finished in the last 30 days) is always a full bar with its number. */
export function StageBars({ stages }: { stages: Stages }) {
  const totals = stages.rows.map((r) => r.running + r.waiting + r.paused);
  const max = Math.max(1, ...totals);
  return (
    <Widget title="Workflows by stage" icon={GitBranch}>
      {totals.every((t) => t === 0) && stages.done_30d === 0 ? (
        <Empty>No workflows in progress.</Empty>
      ) : (
        <>
          {stages.rows.map((row, i) => (
            <Row key={row.stage} label={STAGE_LABEL[row.stage]} total={totals[i]}>
              {SEGMENTS.map((s) => (
                <b key={s.key} data-segment className={`block ${s.className}`} style={{ width: `${(row[s.key] / max) * 100}%` }} />
              ))}
            </Row>
          ))}
          <Row label="Done" total={stages.done_30d}>
            <b className="block w-full bg-green" />
          </Row>
          <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
            {SEGMENTS.map((s) => (
              <span key={s.key} className="inline-flex items-center gap-1">
                <i className={`inline-block size-2.5 rounded-sm ${s.className}`} />
                {s.label}
              </span>
            ))}
            <span className="inline-flex items-center gap-1">
              <i className="inline-block size-2.5 rounded-sm bg-green" />
              finished in the last 30 days
            </span>
          </p>
        </>
      )}
    </Widget>
  );
}
