"use client";

import { useRef, useState } from "react";

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
      <div className="relative">
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
                setMention(null);
                return;
              }
            }
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) e.currentTarget.form?.requestSubmit();
          }}
        />
        {picking && (
          <ul role="listbox" aria-label="Mention someone" className="card absolute left-0 z-20 mt-1 w-60 p-1">
            {options.map((u, i) => (
              <li
                key={u.id}
                role="option"
                aria-selected={i === active}
                className={`cursor-pointer rounded px-2 py-1 text-sm ${i === active ? "bg-surface-2" : ""}`}
                onMouseDown={(e) => e.preventDefault()} // keep the textarea's focus and caret
                onClick={() => pick(u)}
              >
                {u.name}
              </li>
            ))}
          </ul>
        )}
      </div>
      <Button type="submit" disabled={busy || !body.trim()}>Comment</Button>
    </form>
  );
}
