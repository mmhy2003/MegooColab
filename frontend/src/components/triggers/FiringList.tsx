"use client";

import Link from "next/link";

import { ScrollX } from "@/components/ui/ScrollX";
import { RESULT_TEXT, SKIP_TEXT, useFirings, type Firing } from "@/lib/triggers";

/** The excerpt under a firing's result: the skip reason in words, or the reply, question or failure. */
function excerptText(f: Firing) {
  if (!f.excerpt) return null;
  return f.result === "skipped" ? (SKIP_TEXT[f.excerpt] ?? f.excerpt) : f.excerpt;
}

/** A trigger's firings, newest first: what happened, which agent took it, and how its chat went. */
export function FiringList({ projectKey, triggerId }: { projectKey: string; triggerId: string }) {
  const firings = useFirings(projectKey, triggerId);
  if (!firings.data) return null;
  if (firings.data.length === 0) return <p className="text-sm text-muted-foreground">No firings yet.</p>;
  return (
    <ScrollX>
      <table className="w-full text-sm">
        <thead className="text-left text-xs tracking-wider text-muted-foreground uppercase">
          <tr>
            <th className="py-1 pr-3">Fired at</th>
            <th className="py-1 pr-3">What happened</th>
            <th className="py-1 pr-3">Agent</th>
            <th className="py-1">Result</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {firings.data.map((f) => {
            const excerpt = excerptText(f);
            const subject = `${f.subject.label} ${f.subject.title}`;
            return (
              <tr key={f.id} className="align-top">
                <td className="py-2 pr-3 text-xs whitespace-nowrap">{new Date(f.created_at).toLocaleString()}</td>
                <td className="py-2 pr-3">
                  {f.subject.link ? <Link href={f.subject.link}>{subject}</Link> : <span>{subject}</span>}
                  {f.subject.note && <span className="block text-xs text-muted-foreground">{f.subject.note}</span>}
                </td>
                <td className="py-2 pr-3">{f.agent?.name ?? "—"}</td>
                <td className="py-2">
                  {f.chat_id ? <Link href={`/chats/${f.chat_id}`}>{RESULT_TEXT[f.result]}</Link> : <span>{RESULT_TEXT[f.result]}</span>}
                  {excerpt && <span className="block text-xs break-words whitespace-pre-wrap text-muted-foreground">{excerpt}</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </ScrollX>
  );
}
