import Link from "next/link";

import { FreestyleChip } from "@/components/chats/FreestyleChip";
import { chatGroup, stateText, type Chat, type ChatGroup } from "@/lib/chats";

/** Each group's mark at the start of a row, and the colour of its state text: amber waits on a person, a turning cyan
 * ring is an agent at work (still when the system asks for less motion), a green ring is the person's turn, pink is
 * a runner away, grey is over. */
const MARK: Record<ChatGroup, string> = {
  needs_you: "size-2.5 bg-amber shadow-[0_0_0_3px_color-mix(in_oklab,var(--amber)_25%,transparent)]",
  working: "size-2.5 border-2 border-cyan border-r-transparent motion-safe:animate-spin",
  open: "size-2.5 border-2 border-green",
  offline: "size-2.5 bg-pink",
  ended: "size-2.5 bg-line",
};
const TONE: Record<ChatGroup, string> = {
  needs_you: "text-amber",
  working: "text-cyan-ink",
  open: "text-green-ink",
  offline: "text-pink",
  ended: "text-muted-foreground",
};

/** The chats down the side of the Chats page, in the order the server gives (waiting on the viewer first). `empty` is
 * what to say when there are none (a filter can leave none). */
export function ChatList({ chats, selected, showProject, empty = "No chats yet." }: {
  chats: Chat[];
  selected?: string;
  showProject: boolean;
  empty?: string;
}) {
  if (chats.length === 0) return <p className="px-2 py-4 text-sm text-muted-foreground">{empty}</p>;
  return (
    <ul className="space-y-1">
      {chats.map((c) => {
        const group = chatGroup(c);
        return (
          <li key={c.id}>
            <Link
              href={`/chats/${c.id}`}
              data-group={group}
              aria-current={c.id === selected ? "page" : undefined}
              className={`flex items-start gap-2.5 rounded px-2.5 py-2 text-fg no-underline hover:bg-surface-2 ${
                c.id === selected ? "bg-surface-2 shadow-[inset_2px_0_0_var(--cyan)]" : ""
              }`}
            >
              {/* the state text says the same in words, so the mark is for the eye only */}
              <span data-mark aria-hidden className={`mt-1.5 shrink-0 rounded-full ${MARK[group]}`} />
              <span className="min-w-0 flex-1">
                {/* two lines on a phone; one line, cut, on a wide screen. No `block`: it would undo the clamp's display */}
                <span className={`text-sm wrap-anywhere max-md:line-clamp-2 md:block md:truncate ${group === "ended" ? "text-muted-foreground" : ""}`}>
                  {c.title}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {c.mode === "freestyle" && <FreestyleChip className="mr-1.5 px-1 py-0 text-[11px]" />}
                  {showProject && `${c.project_key} · `}
                  <span className={TONE[group]}>{stateText(c)}</span>
                </span>
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
