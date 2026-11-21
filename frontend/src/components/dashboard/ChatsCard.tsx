import { MessageCircle } from "lucide-react";
import Link from "next/link";

import { Empty, Widget } from "@/components/dashboard/Widget";
import { chatStateText, WAITING, type ChatState } from "@/lib/chats";
import type { ChatBrief } from "@/lib/dashboard";

/** Open chats in scope, most recent first, each with what it is doing. */
export function ChatsCard({ chats }: { chats: ChatBrief[] }) {
  return (
    <Widget title="Chats" icon={MessageCircle} more={{ href: "/chats", label: "All chats" }}>
      <p className="-mt-1 mb-1 text-right text-xs">
        <Link href="/chats?new=1">New chat</Link>
      </p>
      {chats.length === 0 ? (
        <Empty>No open chats.</Empty>
      ) : (
        <ul className="divide-y divide-line">
          {chats.map((c) => {
            const state = c.state as ChatState;
            const tone = WAITING.includes(state) ? "text-amber" : state === "building" || state === "in_review" ? "text-cyan-ink" : "text-muted-foreground";
            return (
              <li key={c.id} className="space-y-0.5 py-1.5 text-sm">
                <Link href={`/chats/${c.id}`} className="group flex min-w-0 items-center gap-1.5 text-fg no-underline">
                  <span className="shrink-0 font-mono text-xs text-cyan-ink">{c.project_key}</span>{" "}
                  <span className="min-w-0 truncate group-hover:underline">{c.title}</span>
                </Link>
                <p className={`text-xs break-words ${tone}`}>{chatStateText({ ...c, state })}</p>
              </li>
            );
          })}
        </ul>
      )}
    </Widget>
  );
}
