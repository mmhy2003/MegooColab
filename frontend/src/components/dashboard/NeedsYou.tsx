"use client";

import { Inbox } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";

import { Chip, Empty, type Tone, Widget } from "@/components/dashboard/Widget";
import { minuteAge, type NeedItem } from "@/lib/dashboard";
import { useMarkRead } from "@/lib/notifications";
import { escalationReasonText } from "@/lib/workflow";

const KINDS: Record<NeedItem["kind"], { label: string; tone: Tone; button: string }> = {
  design_approval: { label: "Approve design", tone: "amber", button: "Review" },
  plan_approval: { label: "Approve plan", tone: "amber", button: "Review" },
  question: { label: "Agent asks", tone: "cyan", button: "Answer" },
  escalation: { label: "Stuck", tone: "pink", button: "Look" },
  human_code_review: { label: "Code review", tone: "violet", button: "Review" },
  draft_answer: { label: "Question to send", tone: "cyan", button: "Check" },
  needs_human: { label: "Question needs a person", tone: "amber", button: "Answer" },
  mention: { label: "Mention", tone: "muted", button: "Reply" },
};

const isWebAddress = (url: string | null | undefined): url is string => !!url && /^https?:\/\//i.test(url);

function summary(item: NeedItem): ReactNode {
  switch (item.kind) {
    case "question":
      return item.detail ? `“${item.detail}”` : item.title;
    case "escalation":
      return escalationReasonText(item.detail ?? null);
    case "human_code_review":
      return isWebAddress(item.detail) ? (
        <>
          <a href={item.detail} target="_blank" rel="noopener noreferrer" className="text-cyan-ink hover:underline">Pull request</a>
          {` · ${item.title}`}
        </>
      ) : (
        `Pull request · ${item.title}`
      );
    case "mention":
      return item.detail ? `${item.title}: “${item.detail}”` : item.title;
    default:
      return item.title;
  }
}

const BUTTON = "shrink-0 rounded-sm border border-cyan px-2 py-0.5 text-[11px] font-semibold tracking-wide text-cyan-ink uppercase no-underline hover:bg-surface-2";

/** Reply marks the mention read first (that refreshes the bell, the dashboard and the badge), then opens the task. */
function ReplyButton({ item }: { item: NeedItem }) {
  const markRead = useMarkRead();
  const router = useRouter();
  return (
    <button
      type="button"
      className={BUTTON}
      aria-label={`Reply ${item.ref}`}
      disabled={markRead.isPending}
      // opening the task still helps if marking read fails; the mention then stays until it is read
      onClick={() => markRead.mutate(item.notification_id!, { onSettled: () => router.push(item.link) })}
    >
      Reply
    </button>
  );
}

/** Ticks once a minute: waiting times are shown in minutes or more. */
function useMinuteClock(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);
  return now;
}

/** What waits for a person, longest-waiting first. */
export function NeedsYou({ items, total, showWaitingFor }: { items: NeedItem[]; total: number; showWaitingFor: boolean }) {
  const now = useMinuteClock();
  return (
    <Widget title="Needs you" icon={Inbox} count={total} more={{ href: "/notifications", label: "Open all" }}>
      {items.length === 0 ? (
        <Empty>Nothing needs you.</Empty>
      ) : (
        <ul className="divide-y divide-line">
          {items.map((item) => {
            const kind = KINDS[item.kind];
            return (
              <li key={`${item.kind}:${item.ref}:${item.notification_id ?? ""}`} className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 py-1.5 text-sm">
                <Chip tone={kind.tone}>{kind.label}</Chip>
                {item.ref && <span className="shrink-0 font-mono text-xs text-cyan-ink">{item.ref}</span>}
                <span className="min-w-0 flex-1 basis-32 truncate">{summary(item)}</span>
                <span className="shrink-0 text-xs text-muted-foreground">{minuteAge(now - Date.parse(item.since))}</span>
                {item.kind === "mention" && item.notification_id ? (
                  <ReplyButton item={item} />
                ) : (
                  <Link href={item.link} className={BUTTON} aria-label={`${kind.button} ${item.ref}`}>
                    {kind.button}
                  </Link>
                )}
                {showWaitingFor && item.waiting_for.length > 0 && (
                  <span className="w-full truncate text-xs text-muted-foreground">waits for {item.waiting_for.join(", ")}</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Widget>
  );
}
