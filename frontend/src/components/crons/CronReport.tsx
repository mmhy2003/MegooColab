"use client";

import Link from "next/link";

import { Surface } from "@/components/a2ui/Surface";
import { runOutcome, type CronRun } from "@/lib/crons";
import type { SurfaceMessage } from "@/lib/types";

type Finding = { title: string; detail: string; task_key?: string; created?: boolean };

const PANEL_FAILED = "This run's panel couldn't be drawn. The report below is complete without it.";

const taskHref = (projectKey: string, key: string) => `/projects/${projectKey}/tasks/${key.split("-").pop()}`;

/** One run of a cron: its panel when the agent sent one, its summary, what it found (with the tasks it opened or matched), and what it checked.
 * While the renderer loads, the panel's section is empty and the fixed sections already show. */
export function CronReport({ projectKey, run }: { projectKey: string; run: CronRun }) {
  const report = run.report as
    | { summary?: string; findings?: Finding[]; checked?: string; nothing_new?: boolean; notes?: string[] }
    | null;
  return (
    <article className="card min-w-0 space-y-2 p-4">
      <p className="text-xs text-muted-foreground">
        Run of {new Date(run.scheduled_at).toLocaleString()}
        {run.agent ? ` · ${run.agent.name}` : ""}
        {run.commit ? ` · commit ${run.commit.slice(0, 7)}` : ""}
      </p>
      {!report && <p className="text-sm">{runOutcome(run)}</p>}
      {report && (
        <>
          {run.panel && (
            <section aria-label="Panel" className="space-y-2 border-b border-line pb-3">
              <h3 className="text-sm font-semibold text-cyan-ink">Panel</h3>
              <Surface
                message={run.panel as SurfaceMessage}
                readOnly
                fallback={<p className="text-sm text-muted-foreground">{PANEL_FAILED}</p>}
              />
            </section>
          )}
          <h3 className="text-sm font-semibold text-cyan-ink">Summary</h3>
          <p className="text-sm break-words">{report.summary}</p>
          {(report.findings ?? []).length > 0 && (
            <>
              <h3 className="text-sm font-semibold text-cyan-ink">Findings</h3>
              <ul className="space-y-1 text-sm">
                {(report.findings ?? []).map((f, i) => (
                  <li key={i} className="break-words">
                    <b>{f.title}</b> — {f.detail}
                    {f.task_key && (
                      <>
                        {" → "}
                        <Link href={taskHref(projectKey, f.task_key)}>{f.created ? `${f.task_key} created` : f.task_key}</Link>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
          {report.checked && (
            <>
              <h3 className="text-sm font-semibold text-cyan-ink">Checked</h3>
              <p className="text-sm break-words text-muted-foreground">{report.checked}</p>
            </>
          )}
          {(report.notes ?? []).map((n, i) => (
            <p key={i} className="text-xs text-amber">{n}</p>
          ))}
          {run.status !== "done" && <p className="text-sm text-pink">{runOutcome(run)}</p>}
        </>
      )}
    </article>
  );
}
