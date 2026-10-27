"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { AskQuestion } from "@/components/questions/AskQuestion";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { qk } from "@/lib/queries";
import { type QuestionStatus, STATUS_TONE, statusLine, useTaskQuestions } from "@/lib/questions";

/** The questions a task asked other projects, and asking a new one on the task's behalf (for those who may
 * change the task). */
export function TaskQuestions({ taskKey, canAsk = true }: { taskKey: string; canAsk?: boolean }) {
  const client = useQueryClient();
  const questions = useTaskQuestions(taskKey);
  const [asking, setAsking] = useState(false);
  return (
    <section className="space-y-2">
      <h3 className="text-[11px] tracking-widest text-muted uppercase">Questions to other projects</h3>
      {!!questions.data?.length && (
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
      )}
      {!canAsk ? null : asking ? (
        <>
          <AskQuestion
            taskKey={taskKey}
            onAsked={() => {
              setAsking(false);
              void client.invalidateQueries({ queryKey: qk.task(taskKey) });
            }}
          />
          <Button variant="ghost" onClick={() => setAsking(false)}>
            Cancel
          </Button>
        </>
      ) : (
        <Button variant="ghost" onClick={() => setAsking(true)}>
          Ask another project
        </Button>
      )}
    </section>
  );
}

/** "Waiting on PAY": the task has open questions to these projects. */
export function WaitingBadge({ projects }: { projects: string[] }) {
  if (projects.length === 0) return null;
  return <Badge tone="amber">Waiting on {projects.join(", ")}</Badge>;
}
