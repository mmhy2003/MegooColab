"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { useDraftAgents, type DraftTarget, type KbDraft } from "@/lib/kbDrafts";

const AUTHOR_STYLE = {
  person: "self-end max-w-[90%] border border-line bg-surface-2",
  agent: "max-w-[95%] border border-line",
  system: "text-muted-foreground italic",
} as const;

/** The conversation with the draft's agent: what was asked, what it answered, and the next request, aimed at the whole
 * document or at the selected text. */
export function DraftConversation({
  draft,
  target,
  onClearTarget,
  onSend,
  onStop,
  onAgent,
  pickAgent,
  editing = false,
}: {
  draft: KbDraft;
  target: DraftTarget | null;
  onClearTarget: () => void;
  onSend: (text: string) => Promise<boolean>;
  onStop: () => void;
  onAgent: (agentId: string) => void;
  pickAgent: boolean;
  /** the person's editor is open: a request now would not see their edits */
  editing?: boolean;
}) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const name = draft.agent?.name ?? "The agent";
  const busy = draft.state !== "idle";
  const choosing = pickAgent || !draft.agent;
  const agents = useDraftAgents(draft.space.id, choosing);

  const send = async () => {
    setSending(true);
    if (await onSend(text.trim())) setText("");
    setSending(false);
  };

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <ol aria-label="Conversation" className="flex flex-col gap-2">
        {draft.messages.map((m) => (
          <li key={m.id} className={`rounded px-3 py-2 text-sm break-words whitespace-pre-wrap ${AUTHOR_STYLE[m.author]}`}>
            {m.author !== "system" && (
              <span className="block text-xs text-muted-foreground">{m.author === "person" ? "You" : name}</span>
            )}
            {m.target && <span className="block text-xs text-muted-foreground">About “{m.target.text}”</span>}
            {m.text}
          </li>
        ))}
      </ol>
      {busy && (
        <p className="flex flex-wrap items-center gap-2 text-sm text-amber" role="status">
          {draft.state === "writing" ? `${name} is writing…` : `Waiting for ${name} to come online`}
          <Button variant="danger" className="min-h-8" onClick={onStop}>
            Stop
          </Button>
        </p>
      )}
      {choosing && (
        <Select label="Agent" value="" onChange={(e) => e.target.value && onAgent(e.target.value)}>
          <option value="">Pick an agent</option>
          {(agents.data ?? []).map((a) => (
            <option key={a.id} value={a.id} disabled={!a.runner_ok}>
              {a.name}
              {!a.runner_ok ? " (runner needs updating)" : !a.online ? " (offline)" : ""}
            </option>
          ))}
        </Select>
      )}
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <div className="flex flex-wrap gap-1 text-xs">
          {target && (
            <span className="max-w-full truncate rounded-full border border-cyan px-2 text-cyan-ink">
              About: selected text in &apos;{target.section}&apos;
            </span>
          )}
          <button
            type="button"
            onClick={onClearTarget}
            className={`rounded-full border px-2 ${target ? "border-line text-muted-foreground" : "border-cyan text-cyan-ink"}`}
          >
            whole document
          </button>
        </div>
        <label htmlFor="draft-request" className="sr-only">
          Your request
        </label>
        <textarea
          id="draft-request"
          value={text}
          maxLength={20000}
          onChange={(e) => setText(e.target.value)}
          placeholder="Add a rollback section, shorten the intro, drop the FAQ…"
          className="block min-h-20 w-full rounded border border-line bg-surface-2 p-2 text-sm"
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={busy || editing || sending || !text.trim() || !draft.agent}>
            Send
          </Button>
          {editing && <span className="text-xs text-muted-foreground">Done editing first</span>}
        </div>
      </form>
    </div>
  );
}
