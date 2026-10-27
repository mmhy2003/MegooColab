"use client";

import { stageLabel, useRunRecords, type Decision } from "@/lib/workflow";

function when(at: string): string {
  return new Date(at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function groupLabel(d: Decision): string {
  return d.step != null ? `Step ${d.step}` : stageLabel(d.stage);
}

/** The decisions agents made on their own, grouped by step (stage-level ones last), each with its four fields. */
export function Decisions({ taskKey }: { taskKey: string }) {
  const records = useRunRecords(taskKey);
  const decisions = records.data?.decisions ?? [];
  if (decisions.length === 0) return null;

  const groups = new Map<string, Decision[]>();
  const ordered = [...decisions].sort((a, b) => (a.step ?? Number.MAX_SAFE_INTEGER) - (b.step ?? Number.MAX_SAFE_INTEGER));
  for (const d of ordered) {
    const label = groupLabel(d);
    groups.set(label, [...(groups.get(label) ?? []), d]);
  }

  return (
    <div className="space-y-3 text-sm">
      {[...groups].map(([label, rows]) => (
        <section key={label} aria-label={label} className="space-y-2">
          <h4 className="text-xs font-semibold">{label}</h4>
          <ul className="space-y-2">
            {rows.map((d) => (
              <li key={d.id} className="card space-y-1 p-2">
                <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5">
                  <dt className="text-xs text-muted">Decision</dt>
                  <dd>{d.decision}</dd>
                  {d.plan_said && (
                    <>
                      <dt className="text-xs text-muted">Plan said</dt>
                      <dd>{d.plan_said}</dd>
                    </>
                  )}
                  <dt className="text-xs text-muted">Why</dt>
                  <dd>{d.reason}</dd>
                  <dt className="text-xs text-muted">Cost if wrong</dt>
                  <dd>{d.cost_if_wrong}</dd>
                </dl>
                <p className="text-xs text-muted">
                  {d.author} · {when(d.created_at)}
                </p>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
