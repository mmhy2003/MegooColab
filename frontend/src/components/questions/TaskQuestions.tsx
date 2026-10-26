"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/Badge";
import { type QuestionStatus, STATUS_TONE, statusLine, useTaskQuestions } from "@/lib/questions";

/** The questions a task asked other projects. */
export function TaskQuestions({ taskKey }: { taskKey: string }) {
  const questions = useTaskQuestions(taskKey);
  if (!questions.data?.length) return null;
  return (
    <section className="space-y-2">
      <h3 className="text-[11px] tracking-widest text-muted uppercase">Questions to other projects</h3>
      <ul aria-label="Questions to other projects" className="space-y-1">
        {questions.data.map((q) => (
          <li key={q.id} className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-mono text-xs text-muted">{q.ref}</span>
            <Link href={`/questions/${q.id}`} className="min-w-0 flex-1 truncate">
              {q.title}
            </Link>
            <Badge tone={STATUS_TONE[q.status as QuestionStatus] ?? "muted"}>{statusLine(q)}</Badge>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** "Waiting on PAY": the task has open questions to these projects. */
export function WaitingBadge({ projects }: { projects: string[] }) {
  if (projects.length === 0) return null;
  return <Badge tone="amber">Waiting on {projects.join(", ")}</Badge>;
}
