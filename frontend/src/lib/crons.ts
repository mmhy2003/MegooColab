"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";

type S = components["schemas"];

export type Cron = S["CronOut"];
export type CronRun = S["CronRunOut"];
export type CronMode = Cron["mode"];
export type SchedulePreview = S["Preview"];

export const cronKeys = {
  all: ["crons"] as const,
  list: (project: string) => ["crons", project] as const,
  one: (project: string, id: string) => ["crons", project, id] as const,
  runs: (project: string, id: string) => ["crons", project, id, "runs"] as const,
};

export const cronsPath = (project: string) => `/api/projects/${project}/crons`;

export function useCrons(project: string) {
  return useQuery({ queryKey: cronKeys.list(project), queryFn: () => api<Cron[]>(cronsPath(project)) });
}

export function useCron(project: string, id: string) {
  return useQuery({ queryKey: cronKeys.one(project, id), queryFn: () => api<Cron>(`${cronsPath(project)}/${id}`) });
}

export function useCronRuns(project: string, id: string) {
  return useQuery({
    queryKey: cronKeys.runs(project, id),
    queryFn: () => api<CronRun[]>(`${cronsPath(project)}/${id}/runs`),
  });
}

export function previewSchedule(schedule: string, timezone: string): Promise<SchedulePreview> {
  return api<SchedulePreview>("/api/crons/preview", { method: "POST", json: { schedule, timezone } });
}

const REASONS: Record<string, string> = {
  previous_running: "skipped: the previous run was still going",
  missed: "skipped: MegooColab was down at that time",
  no_agent_online: "skipped: no agent online",
  no_agent: "skipped: no agent can work on this project",
  timed_out: "failed: stopped after 30 minutes",
  made_a_commit: "failed: the agent made a commit (it was thrown away)",
  no_report: "failed: the agent finished without a report",
};

/** How a run went, in a few words. */
export function runOutcome(run: CronRun): string {
  if (run.status === "queued") return "waiting for an agent";
  if (run.status === "running") return "running";
  if (run.status === "skipped" || run.status === "failed") {
    return REASONS[run.skip_reason ?? ""] ?? `${run.status}${run.skip_reason ? `: ${run.skip_reason}` : ""}`;
  }
  const findings = ((run.report?.findings as unknown[]) ?? []).length;
  if (run.report?.nothing_new && !findings) return "nothing new";
  const created = run.tasks_created ? ` · ${run.tasks_created} task${run.tasks_created === 1 ? "" : "s"} created` : "";
  return `${findings} finding${findings === 1 ? "" : "s"}${created}`;
}

export const browserZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
