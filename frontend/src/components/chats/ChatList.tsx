import Link from "next/link";

import { stateText, WAITING, type Chat } from "@/lib/chats";

/** The chats down the side of the Chats page, in the order the server gives (waiting on the viewer first). */
export function ChatList({ chats, selected, showProject }: { chats: Chat[]; selected?: string; showProject: boolean }) {
  if (chats.length === 0) return <p className="px-2 py-4 text-sm text-muted-foreground">No chats yet.</p>;
  return (
    <ul className="space-y-1">
      {chats.map((c) => {
        const waiting = c.can_act && WAITING.includes(c.state);
        const tone = waiting ? "text-amber" : c.state === "finished" ? "text-green" : "text-muted-foreground";
        return (
          <li key={c.id}>
            <Link
              href={`/chats/${c.id}`}
              aria-current={c.id === selected ? "page" : undefined}
              className={`block rounded px-2.5 py-2 text-fg no-underline hover:bg-surface-2 ${
                c.id === selected ? "bg-surface-2 shadow-[inset_2px_0_0_var(--cyan)]" : ""
              }`}
            >
              {/* two lines on a phone; one line, cut, on a wide screen. No `block`: it would undo the clamp's display */}
              <span className="text-sm wrap-anywhere max-md:line-clamp-2 md:block md:truncate">{c.title}</span>
              <span className={`block truncate text-xs ${tone}`}>
                {showProject && `${c.project_key} · `}
                {stateText(c)}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
