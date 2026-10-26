"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";

type S = components["schemas"];

export type Question = S["QuestionOut"];
export type QuestionSuggestion = S["Suggestion"];
export type QuestionTarget = S["Target"];
export type AskQuestionOut = S["AskQuestionOut"];
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
