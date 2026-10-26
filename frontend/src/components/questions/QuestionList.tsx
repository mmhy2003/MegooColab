import Link from "next/link";

import { Badge } from "@/components/ui/Badge";
import { type Question, type QuestionStatus, STATUS_TONE, statusLine } from "@/lib/questions";

/** Questions, newest first; drafts the reader may approve come first. */
export function QuestionList({ questions, empty = "No questions yet." }: { questions: Question[]; empty?: string }) {
  if (questions.length === 0) return <p className="text-sm text-muted">{empty}</p>;
  const sorted = [...questions].sort((a, b) => Number(b.can_approve) - Number(a.can_approve));
  return (
    <ul className="divide-y divide-line rounded border border-line">
      {sorted.map((q) => (
        <li key={q.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
          <span className="font-mono text-xs text-muted">{q.ref}</span>
          <Link href={`/questions/${q.id}`} className="min-w-0 flex-1 truncate">
            {q.title}
          </Link>
          {q.can_approve && <Badge tone="amber">Your approval</Badge>}
          <Badge tone={STATUS_TONE[q.status as QuestionStatus] ?? "muted"}>{statusLine(q)}</Badge>
        </li>
      ))}
    </ul>
  );
}
