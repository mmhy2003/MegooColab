"use client";

import { useRef, useState } from "react";

import { Command, CommandItem, CommandList } from "@/components/shadcn/command";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/shadcn/popover";
import { Button } from "@/components/ui/Button";
import { mentionToken } from "@/lib/notifications";

type Person = { id: string; name: string };

const MAX_OPTIONS = 8;
// "@" at the start or after a space, then the name typed so far (an email address never matches)
const TYPING_MENTION = /(^|\s)@([^\s@[\]()]{0,40})$/;

function matching(users: Person[], query: string): Person[] {
  const q = query.toLowerCase();
  return users
    .filter((u) => u.name.toLowerCase().split(/\s+/).some((w) => w.startsWith(q)))
    .slice(0, MAX_OPTIONS);
}

export function CommentBox({ users = [], onSubmit }: { users?: Person[]; onSubmit: (body: string) => Promise<void> }) {
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [mention, setMention] = useState<{ start: number; end: number; query: string } | null>(null);
  const [active, setActive] = useState(0);
  const box = useRef<HTMLTextAreaElement>(null);
  const options = mention ? matching(users, mention.query) : [];
  const picking = options.length > 0;

  const track = (value: string, caret: number) => {
    const m = TYPING_MENTION.exec(value.slice(0, caret));
    setMention(m ? { start: caret - m[2].length - 1, end: caret, query: m[2] } : null);
    setActive(0);
  };

  const pick = (user: Person) => {
    if (!mention) return;
    const token = `${mentionToken(user)} `;
    const next = body.slice(0, mention.start) + token + body.slice(mention.end);
    const caret = mention.start + token.length;
    setBody(next);
    setMention(null);
    requestAnimationFrame(() => box.current?.setSelectionRange(caret, caret));
  };

  return (
    <form
      className="space-y-2"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!body.trim()) return;
        setBusy(true);
        try {
          await onSubmit(body);
          setBody("");
        } finally {
          setBusy(false);
        }
      }}
    >
      {/* the list opens under the comment like a dropdown: no blur, the cursor stays in the comment */}
      <Popover open={picking} onOpenChange={(open) => !open && setMention(null)}>
        <PopoverAnchor asChild>
          <textarea
            ref={box}
            aria-label="Add a comment"
            placeholder="Add a comment (Markdown supported, @ to mention someone)"
            className="min-h-20 w-full rounded border border-line bg-surface-2 p-2 text-sm"
            value={body}
            aria-autocomplete="list"
            onChange={(e) => {
              setBody(e.target.value);
              track(e.target.value, e.target.selectionStart ?? e.target.value.length);
            }}
            onKeyDown={(e) => {
              if (picking) {
                if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                  e.preventDefault();
                  const step = e.key === "ArrowDown" ? 1 : -1;
                  setActive((i) => (i + step + options.length) % options.length);
                  return;
                }
                if ((e.key === "Enter" && !e.metaKey && !e.ctrlKey) || e.key === "Tab") {
                  e.preventDefault();
                  pick(options[Math.min(active, options.length - 1)]);
                  return;
                }
                if (e.key === "Escape") {
                  e.preventDefault();
                  e.stopPropagation(); // closes the list only, not the task drawer around it
                  setMention(null);
                  return;
                }
              }
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) e.currentTarget.form?.requestSubmit();
            }}
          />
        </PopoverAnchor>
        <PopoverContent
          align="start"
          className="w-60 p-1"
          onOpenAutoFocus={(e) => e.preventDefault()} // keep the cursor in the comment
          // Radix closes the list on Escape before the textarea sees the key: stop it there, or the drawer closes too
          // (only while open: once closed, the list fades out still listening, and lets Escape through)
          onEscapeKeyDown={(e) => picking && e.stopPropagation()}
          onInteractOutside={(e) => {
            if (e.target === box.current) e.preventDefault(); // clicking in the comment keeps the list
          }}
        >
          <Command shouldFilter={false} value={options[Math.min(active, options.length - 1)]?.id ?? ""}>
            <CommandList label="Mention someone">
              {options.map((u) => (
                <CommandItem
                  key={u.id}
                  value={u.id}
                  onMouseDown={(e) => e.preventDefault()} // keep the textarea's focus and caret
                  onSelect={() => pick(u)}
                >
                  {u.name}
                </CommandItem>
              ))}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      <Button type="submit" disabled={busy || !body.trim()}>Comment</Button>
    </form>
  );
}
