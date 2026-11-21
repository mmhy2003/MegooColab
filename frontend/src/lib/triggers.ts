"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";

type S = components["schemas"];

export type Trigger = S["TriggerOut"];
export type Firing = S["FiringOut"];
export type TriggerEventId = "task_finished" | "task_created" | "task_moved" | "task_needs_person"
  | "sprint_started" | "sprint_completed" | "epic_completed" | "cron_found" | "pr_merged";
export type TaskTypeName = "story" | "task" | "bug";
export type TriggerConfig = { task_types?: TaskTypeName[]; label_id?: string | null; column_id?: string; cron_id?: string | null };

export const triggerKeys = {
  all: ["triggers"] as const,
  list: (project: string) => ["triggers", project] as const,
  one: (project: string, id: string) => ["triggers", project, id] as const,
  firings: (project: string, id: string) => ["triggers", project, id, "firings"] as const,
};

export const triggersPath = (project: string) => `/api/projects/${project}/triggers`;

export function useTriggers(project: string) {
  return useQuery({ queryKey: triggerKeys.list(project), queryFn: () => api<Trigger[]>(triggersPath(project)) });
}

export function useTrigger(project: string, id: string) {
  return useQuery({ queryKey: triggerKeys.one(project, id), queryFn: () => api<Trigger>(`${triggersPath(project)}/${id}`) });
}

export function useFirings(project: string, id: string) {
  return useQuery({
    queryKey: triggerKeys.firings(project, id),
    queryFn: () => api<Firing[]>(`${triggersPath(project)}/${id}/firings`),
  });
}

export type EventInfo = {
  id: TriggerEventId;
  label: string;
  group: "Task events" | "Sprint events" | "Chains and larger events";
  fields: ("types" | "column" | "cron" | "webhook")[];
  sprints?: true;
  canTry: boolean;
  example: string;
};

const HOST = "https://colab.example.com";
const TASK = `Task PAY-12 "Fix the login redirect" (bug; labels: backend)`;
const TASK_TAIL = `Link: ${HOST}/projects/PAY/tasks/12\nEpic: PAY-3 "Sign-in"\n\nDescription:\nAfter signing in, people land on the home page instead of the page they asked for.`;
const SPRINT_TASKS = "Tasks:\n- PAY-12 [Done] Fix the login redirect\n- PAY-14 [In progress] Export invoices as CSV";

/** The nine events, in the order the editor offers them. `example` is a sample of the What happened block. */
export const EVENTS: EventInfo[] = [
  { id: "task_finished", label: "A task is finished", group: "Task events", fields: ["types"], canTry: true,
    example: `${TASK}\nEvent: finished by Mia\n${TASK_TAIL}` },
  { id: "task_created", label: "A task is created", group: "Task events", fields: ["types"], canTry: true,
    example: `${TASK}\nEvent: created by Mia\n${TASK_TAIL}` },
  { id: "task_moved", label: "A task is moved to a column", group: "Task events", fields: ["column", "types"], canTry: true,
    example: `${TASK}\nEvent: moved from Backlog to Ready by Mia\n${TASK_TAIL}` },
  { id: "task_needs_person", label: "A task needs a person", group: "Task events", fields: ["types"], canTry: true,
    example: `${TASK}\nEvent: escalated: review not clean by the workflow\n${TASK_TAIL}` },
  { id: "sprint_started", label: "A sprint is started", group: "Sprint events", fields: [], sprints: true, canTry: true,
    example: `Sprint "Sprint 7" was started.\nDates: 2026-11-16 to 2026-11-29\nGoal: Invoices can be exported\nLink: ${HOST}/projects/PAY/backlog\n\n${SPRINT_TASKS}` },
  { id: "sprint_completed", label: "A sprint is completed", group: "Sprint events", fields: [], sprints: true, canTry: true,
    example: `Sprint "Sprint 7" was completed.\nDates: 2026-11-16 to 2026-11-29\nGoal: Invoices can be exported\nPoints: 13 of 16 committed points completed\nLink: ${HOST}/projects/PAY/backlog\n\n${SPRINT_TASKS}` },
  { id: "epic_completed", label: "An epic is completed", group: "Chains and larger events", fields: [], canTry: true,
    example: `Epic PAY-3 "Sign-in" was completed: every task of it is in a Done column.\nEvent: PAY-12 "Fix the login redirect" was the last to finish\nLink: ${HOST}/projects/PAY/tasks/3\n\nDescription:\nPeople sign in with their work account.\n\nTasks:\n- PAY-11 [Done] Sign in with SSO\n- PAY-12 [Done] Fix the login redirect` },
  { id: "cron_found", label: "A cron finds something", group: "Chains and larger events", fields: ["cron"], canTry: true,
    example: `Cron "Nightly deps" finished a run on 2026-11-20 02:00 UTC with 1 finding.\nLink: ${HOST}/projects/PAY/crons\n\nSummary:\nOne dependency has a known vulnerability.\n\nFindings:\n- jsonwebtoken 8.5.1: Vulnerable to CVE-2022-23529. (task PAY-88)` },
  { id: "pr_merged", label: "A pull request is merged outside a task", group: "Chains and larger events", fields: ["webhook"], canTry: false,
    example: `Pull request #42 "Bump the README" was merged into main of repository payments by mia.\nBranch: docs/readme\nURL: https://github.com/acme/payments/pull/42` },
];

export const RESULT_TEXT: Record<Firing["result"], string> = {
  starting: "Starting",
  waiting_agent: "Waiting for the agent",
  working: "Working",
  question: "Asked a question",
  replied: "Replied",
  failed: "Couldn't finish",
  skipped: "Skipped",
};

/** Why a firing was skipped: the backend's words (triggers/fire.py SKIP_TEXT), capitalised. */
export const SKIP_TEXT: Record<string, string> = {
  no_agent: "No agent can take it",
  owner_gone: "The person it runs as can no longer start chats here",
  rate_limited: "It already started 20 chats in the last hour",
  paused: "The trigger was paused",
};

export const BROKEN_TEXT: Record<NonNullable<Trigger["broken"]>, string> = {
  column_deleted: "its column was deleted",
  label_deleted: "its label was deleted",
  cron_deleted: "its cron was deleted",
};

export function eventInfo(id: string): EventInfo | undefined {
  return EVENTS.find((e) => e.id === id);
}

/** The trigger's filter in a few words: "story, task, bug · label backend", "to Ready · bug", "Nightly deps",
 * "any cron", or "" when the event has none. A reference that is not (or no longer) known shows as "—". */
export function filterText(
  t: Trigger,
  names: { columns: Map<string, string>; labels: Map<string, string>; crons: Map<string, string> },
): string {
  const config = t.config as TriggerConfig;
  const fields = eventInfo(t.event)?.fields ?? [];
  const parts: string[] = [];
  if (fields.includes("column")) parts.push(`to ${names.columns.get(config.column_id ?? "") ?? "—"}`);
  if (fields.includes("types")) {
    parts.push((config.task_types ?? []).join(", "));
    if (config.label_id) parts.push(`label ${names.labels.get(config.label_id) ?? "—"}`);
  }
  if (fields.includes("cron")) parts.push(config.cron_id ? (names.crons.get(config.cron_id) ?? "—") : "any cron");
  return parts.join(" · ");
}
