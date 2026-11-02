"use client";

import { Fragment, useLayoutEffect, useRef, useState } from "react";

import { Command, CommandItem, CommandList } from "@/components/shadcn/command";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/shadcn/popover";
import { Button } from "@/components/ui/Button";
import { hasAgentMention, removeAgentMentions } from "@/lib/agentMessages";
import { encodeMentions, mentionAt, mentionRanges, type PickedMention } from "@/lib/mentions";

type Person = { id: string; name: string };
type Option = Person & { agent?: boolean };

const MAX_OPTIONS = 8;
// "@" at the start or after a space, then the name typed so far (an email address never matches)
const TYPING_MENTION = /(^|\s)@([^\s@[\]()]{0,40})$/;

function matching(people: Option[], query: string): Option[] {
  const q = query.toLowerCase();
  return people
    .filter((u) => u.name.toLowerCase().split(/[\s_-]+/).some((w) => w.startsWith(q)) || u.name.toLowerCase().startsWith(q))
    .slice(0, MAX_OPTIONS);
}

/** A comment, or with the switch on (or the agent @mentioned), a message for the task's agent: an instruction it
 * reads in the turn it is working on, or at its next run. Only people who direct the task's work may send one
 * (`canTellAgent`); after each send the box goes back to an ordinary comment. */
export function CommentBox({
  users = [],
  agent = null,
  canTellAgent = false,
  hint,
  onSubmit,
}: {
  users?: Person[];
  agent?: Person | null;
  canTellAgent?: boolean;
  hint?: string;
  onSubmit: (body: string, toAgent: boolean) => Promise<void>;
}) {
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [manualOn, setManualOn] = useState(false);
  const [focused, setFocused] = useState(false);
  const [mention, setMention] = useState<{ start: number; end: number; query: string } | null>(null);
  // who was picked from the list: the box shows `@Name`, and their tokens are written only when it is sent
  const [picked, setPicked] = useState<PickedMention[]>([]);
  const [active, setActive] = useState(0);
  const box = useRef<HTMLTextAreaElement>(null);
  const backdrop = useRef<HTMLDivElement>(null);
  const caretAfter = useRef<number | null>(null);
  useLayoutEffect(() => {
    if (caretAfter.current === null) return;
    box.current?.setSelectionRange(caretAfter.current, caretAfter.current);
    caretAfter.current = null;
  }, [body]);
  const tellable = agent !== null && canTellAgent;
  const sent = encodeMentions(body, picked);
  const toAgent = tellable && (manualOn || hasAgentMention(sent, agent.id));
  const ranges = mentionRanges(body, picked);
  const people: Option[] = tellable ? [{ ...agent, agent: true }, ...users] : users;
  const options = mention ? matching(people, mention.query) : [];
  const picking = options.length > 0;

  const track = (value: string, caret: number) => {
    const m = TYPING_MENTION.exec(value.slice(0, caret));
    setMention(m ? { start: caret - m[2].length - 1, end: caret, query: m[2] } : null);
    setActive(0);
  };

  const pick = (user: Option) => {
    if (!mention) return;
    const shown = `@${user.name} `;
    const next = body.slice(0, mention.start) + shown + body.slice(mention.end);
    const caret = mention.start + shown.length;
    setBody(next);
    setPicked((p) => (p.some((m) => m.id === user.id) ? p : [...p, { id: user.id, name: user.name, agent: user.agent }]));
    setMention(null);
    caretAfter.current = caret; // placed as soon as the new text renders, before the next keystroke
  };

  return (
    <form
      className="space-y-2"
      data-to-agent={toAgent || undefined}
      onSubmit={async (e) => {
        e.preventDefault();
        if (!body.trim()) return;
        setBusy(true);
        try {
          await onSubmit(sent, toAgent);
          setBody("");
          setPicked([]);
          setManualOn(false);
        } finally {
          setBusy(false);
        }
      }}
    >
      {/* the list opens under the comment like a dropdown: no blur, the cursor stays in the comment */}
      <Popover open={picking} onOpenChange={(open) => !open && setMention(null)}>
        <PopoverAnchor asChild>
          {/* the mentions are highlighted on a copy of the text behind the (transparent) box, laid out the same way */}
          <div className="relative rounded bg-surface-2">
            <div
              ref={backdrop}
              aria-hidden
              className="pointer-events-none absolute inset-0 overflow-hidden rounded border border-transparent p-2 text-sm break-words whitespace-pre-wrap text-transparent"
            >
              {ranges.map((r, i) => (
                <Fragment key={r.start}>
                  {body.slice(i === 0 ? 0 : ranges[i - 1].end, r.start)}
                  <mark className={`rounded text-transparent ${r.mention.agent ? "bg-violet/30" : "bg-cyan/25"}`}>{body.slice(r.start, r.end)}</mark>
                </Fragment>
              ))}
              {body.slice(ranges.at(-1)?.end ?? 0)}
              {"\u200b" /* a final newline still takes its line */}
            </div>
            <textarea
              ref={box}
              aria-label="Add a comment"
              placeholder="Add a comment (Markdown supported, @ to mention someone)"
              // on a phone, an empty box waiting at the bottom is one line: it grows when tapped
              className={`relative block w-full rounded border bg-transparent p-2 text-sm ${toAgent ? "border-violet" : "border-line"} ${
                focused || body ? "min-h-20" : "h-9 min-h-9 resize-none sm:h-auto sm:min-h-20"
              }`}
              onScroll={(e) => {
                if (backdrop.current) backdrop.current.scrollTop = e.currentTarget.scrollTop;
              }}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
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
                if (e.key === "Backspace") {
                  const { selectionStart: at, selectionEnd } = e.currentTarget;
                  const whole = at === selectionEnd ? mentionAt(body, picked, at) : null;
                  if (whole) {
                    // a mention goes as one: half a name would be sent as plain text
                    e.preventDefault();
                    setBody(body.slice(0, whole.start) + body.slice(whole.end));
                    caretAfter.current = whole.start;
                    return;
                  }
                }
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) e.currentTarget.form?.requestSubmit();
              }}
            />
          </div>
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
                  {u.agent && <span className="ml-1 text-xs text-muted-foreground">· agent on this task</span>}
                </CommandItem>
              ))}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          role="switch"
          aria-checked={toAgent}
          aria-label={`Send to ${agent?.name ?? "the agent"}`}
          disabled={!tellable}
          onClick={() => {
            if (toAgent) {
              setManualOn(false);
              if (agent) {
                // the agent's mentions go, picked ones (shown as @Name) and any typed as a token
                const mine = mentionRanges(body, picked).filter((r) => r.mention.agent && r.mention.id === agent.id);
                let next = body;
                for (const r of [...mine].reverse()) next = next.slice(0, r.start) + next.slice(r.end).replace(/^ /, "");
                setBody(removeAgentMentions(next, agent.id));
              }
            } else {
              setManualOn(true);
            }
          }}
          className={`inline-flex items-center gap-2 text-xs disabled:cursor-not-allowed disabled:opacity-60 ${toAgent ? "text-violet" : "text-muted-foreground"}`}
        >
          <span aria-hidden className={`relative h-4 w-7 rounded-full transition-colors ${toAgent ? "bg-violet/45" : "bg-line"}`}>
            <span className={`absolute top-0.5 size-3 rounded-full transition-all ${toAgent ? "left-3.5 bg-violet" : "left-0.5 bg-muted-foreground"}`} />
          </span>
          Send to {agent?.name ?? "the agent"}
        </button>
        <Button
          type="submit"
          className={`ml-auto ${toAgent ? "border-violet bg-violet text-on-accent dark:bg-violet" : ""}`}
          disabled={busy || !body.trim()}
        >
          {toAgent ? "Send to agent" : "Comment"}
        </Button>
      </div>
      {!agent && <p className="text-xs text-muted-foreground">No agent is assigned to this task.</p>}
      {agent && !canTellAgent && (
        <p className="text-xs text-muted-foreground">Only {agent.name}&apos;s owner and the project&apos;s managers can send it messages.</p>
      )}
      {toAgent && hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </form>
  );
}
