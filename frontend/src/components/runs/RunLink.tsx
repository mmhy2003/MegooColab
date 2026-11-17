import Link from "next/link";

import type { RunningItem } from "@/lib/dashboard";

const TAG = { chat: "border-violet text-violet", cron: "border-line text-muted-foreground" } as const;

/** What a run works on, as a link: a task's key, a chat's or cron's tag and title, a question's key. A draft, or a
 *  run the viewer cannot open, is the same text without the link. A key never shortens; a title does. */
export function RunLink({ run }: { run: RunningItem }) {
  const keyed = run.kind === "task" || run.kind === "question";
  const text =
    run.kind === "task" ? run.task_key
    : run.kind === "question" ? run.question_key
    : run.kind === "draft" ? "Knowledge Base draft"
    : run.title;
  const look = keyed ? "shrink-0 font-mono text-xs" : "min-w-0 truncate";
  const tag = run.kind === "chat" || run.kind === "cron" ? run.kind : null;
  return (
    <>
      {tag && <span className={`shrink-0 rounded border px-1 text-[10px] uppercase ${TAG[tag]}`}>{tag}</span>}
      {run.link ? (
        <Link
          href={run.link}
          title={run.kind === "task" ? (run.title ?? undefined) : undefined}
          className={`${look} text-cyan-ink no-underline hover:underline`}
        >
          {text ?? run.kind}
        </Link>
      ) : (
        <span className={look}>{text ?? run.kind}</span>
      )}
    </>
  );
}
