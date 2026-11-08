"use client";

import { useQuery } from "@tanstack/react-query";

import { PROGRAM_LABEL } from "@/lib/agents";
import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";

type S = components["schemas"];

export type Question = S["QuestionOut"];
export type QuestionSuggestion = S["Suggestion"];
export type QuestionTarget = S["Target"];
export type AskQuestionOut = S["AskQuestionOut"];
export type TargetAgent = S["TargetAgent"];
export type QuestionStatus = "queued" | "routed" | "draft" | "needs_human" | "answered" | "withdrawn";
export type QuestionBox = "mine" | "incoming";

export const QUESTION_STATUSES: { value: QuestionStatus; label: string }[] = [
  { value: "queued", label: "Waiting for a runner" },
  { value: "routed", label: "Being answered" },
  { value: "draft", label: "Draft" },
  { value: "needs_human", label: "Needs a human" },
  { value: "answered", label: "Answered" },
  { value: "withdrawn", label: "Withdrawn" },
];

/** Every questions query starts with "questions", so one invalidation (question.* events) refreshes them all. */
export const questionKeys = {
  all: ["questions"] as const,
  list: (box: QuestionBox, project: string, status: string) => ["questions", "list", box, project, status] as const,
  one: (id: string) => ["questions", "one", id] as const,
  task: (key: string) => ["questions", "task", key] as const,
  targets: () => ["questions", "targets"] as const,
  targetAgents: (key: string) => ["questions", "targets", key, "agents"] as const,
};

export function useQuestions(box: QuestionBox, project = "", status = "") {
  const params = new URLSearchParams({ box });
  if (project) params.set("project", project);
  if (status) params.set("status", status);
  return useQuery({
    queryKey: questionKeys.list(box, project, status),
    queryFn: () => api<Question[]>(`/api/questions?${params}`),
  });
}

export function useQuestion(id: string) {
  return useQuery({ queryKey: questionKeys.one(id), queryFn: () => api<Question>(`/api/questions/${id}`) });
}

export function useTaskQuestions(taskKey: string) {
  return useQuery({
    queryKey: questionKeys.task(taskKey),
    queryFn: () => api<Question[]>(`/api/tasks/${taskKey}/questions`),
  });
}

export function useQuestionTargets() {
  return useQuery({ queryKey: questionKeys.targets(), queryFn: () => api<QuestionTarget[]>("/api/questions/targets") });
}

/** The agents that can answer a project's questions, free, busy or offline now (none while no project is chosen). */
export function useTargetAgents(key: string) {
  return useQuery({
    queryKey: questionKeys.targetAgents(key),
    queryFn: () => api<TargetAgent[]>(`/api/questions/targets/${key}/agents`),
    enabled: key !== "",
  });
}

const PROGRAM_NAME: Record<string, string> = PROGRAM_LABEL;

/** "For: Claude Code agents · waits if busy"; null for any free agent. */
export function preferenceLine(p: Question["preference"]): string | null {
  if (!p) return null;
  const who = p.agent ? p.agent.name : p.program ? `${PROGRAM_NAME[p.program] ?? p.program} agents` : "a chosen agent";
  return `For: ${who} · ${p.if_busy === "wait" ? "waits if busy" : "another agent if busy"}`;
}

function whoName(who: Question["answered_by"] | null | undefined): string {
  if (!who) return "someone";
  if (who.agent && who.user) return `${who.agent.name} (${who.user.name})`;
  return who.agent?.name ?? who.user?.name ?? "someone";
}

/** One line on where the question stands. */
export function statusLine(q: Question): string {
  switch (q.status as QuestionStatus) {
    case "queued":
      return `Waiting for a runner of ${q.target.key}`;
    case "routed":
      return `Being answered by ${q.answering?.agent?.name ?? "an agent"}`;
    case "draft":
      return `Draft awaiting ${q.answering?.user?.name ?? "the agent owner"}'s approval`;
    case "needs_human":
      return "Needs a human answer";
    case "answered":
      return `Answered by ${whoName(q.answered_by)}`;
    case "withdrawn":
      return "Withdrawn";
    default:
      return q.status;
  }
}

export const STATUS_TONE: Record<QuestionStatus, "cyan" | "pink" | "green" | "muted" | "amber"> = {
  queued: "muted",
  routed: "cyan",
  draft: "amber",
  needs_human: "pink",
  answered: "green",
  withdrawn: "muted",
};

export function citationText(c: { path: string; start_line: number; end_line: number }): string {
  return `${c.path}:${c.start_line}-${c.end_line}`;
}

export type ProjectWait = S["ProjectWaitOut"];

/** "ANS-Q3" -> "ANS". */
export function refProject(ref: string): string {
  return ref.replace(/-Q\d+$/, "");
}

/** "ANS" / "ANS and PAY" / "ANS, PAY and OPS". */
function joinKeys(keys: string[]): string {
  return keys.length <= 1 ? keys.join("") : `${keys.slice(0, -1).join(", ")} and ${keys[keys.length - 1]}`;
}

/** What a task waits for, from its questions' refs: "ANS's answer (ANS-Q3)", or "answers from ANS and PAY (2)". */
export function waitingFor(refs: string[], withRef = true): string {
  if (refs.length === 0) return "another project's answer";
  if (refs.length === 1) return `${refProject(refs[0])}'s answer${withRef ? ` (${refs[0]})` : ""}`;
  return `answers from ${joinKeys([...new Set(refs.map(refProject))])} (${refs.length})`;
}

/** Where a question the task waits for stands, in the asker's words. */
export function waitStatusLine(status: string, key: string): string {
  switch (status) {
    case "queued":
      return `waiting for an agent of ${key}`;
    case "routed":
      return `an agent of ${key} is answering`;
    case "draft":
      return `the answer waits for approval at ${key}`;
    case "needs_human":
      return `waiting for a person at ${key}`;
    case "answered":
      return "answered";
    default:
      return status;
  }
}

/** Each follow-up straight after the question it follows (and its own follow-ups after it); the rest in order. */
export function withFollowUps(questions: Question[]): { question: Question; followUp: boolean }[] {
  const ids = new Set(questions.map((q) => q.id));
  const children = new Map<string, Question[]>();
  for (const q of questions) {
    const parent = q.follow_up_of?.id;
    if (parent && ids.has(parent)) children.set(parent, [...(children.get(parent) ?? []), q]);
  }
  const out: { question: Question; followUp: boolean }[] = [];
  const add = (q: Question, followUp: boolean) => {
    out.push({ question: q, followUp });
    for (const c of children.get(q.id) ?? []) add(c, true);
  };
  for (const q of questions) {
    if (!(q.follow_up_of?.id && ids.has(q.follow_up_of.id))) add(q, false);
  }
  return out;
}
