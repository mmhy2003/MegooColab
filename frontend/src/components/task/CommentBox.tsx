"use client";

import { useRef, useState } from "react";

import { Command, CommandItem, CommandList } from "@/components/shadcn/command";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/shadcn/popover";
import { Button } from "@/components/ui/Button";
import { agentMentionToken, hasAgentMention, removeAgentMentions } from "@/lib/agentMessages";
import { mentionToken } from "@/lib/notifications";

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
  const [active, setActive] = useState(0);
  const box = useRef<HTMLTextAreaElement>(null);
  const tellable = agent !== null && canTellAgent;
  const toAgent = tellable && (manualOn || hasAgentMention(body, agent.id));
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
    const token = `${user.agent ? agentMentionToken(user) : mentionToken(user)} `;
    const next = body.slice(0, mention.start) + token + body.slice(mention.end);
    const caret = mention.start + token.length;
    setBody(next);
    setMention(null);
    requestAnimationFrame(() => box.current?.setSelectionRange(caret, caret));
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
          await onSubmit(body, toAgent);
          setBody("");
          setManualOn(false);
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
            // on a phone, an empty box waiting at the bottom is one line: it grows when tapped
            className={`w-full rounded border bg-surface-2 p-2 text-sm ${toAgent ? "border-violet" : "border-line"} ${
              focused || body ? "min-h-20" : "h-9 min-h-9 resize-none sm:h-auto sm:min-h-20"
            }`}
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
              if (agent) setBody((b) => removeAgentMentions(b, agent.id));
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
