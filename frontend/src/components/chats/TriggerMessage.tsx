import type { Chat } from "@/lib/chats";

/** Marks a chat a trigger started (the chat's header, its row in the list). */
export function TriggerChip({ className = "" }: { className?: string }) {
  return <span className={`rounded border border-amber px-1.5 text-xs text-amber ${className}`}>Trigger</span>;
}

/** A triggered chat's first message: the trigger and the person it runs as, its prompt, and the "What happened"
 * block the agent was given with it. */
export function TriggerMessage({ chat, prompt }: { chat: Chat; prompt: string }) {
  if (!chat.trigger) return null;
  return (
    <section aria-label="First message" className="space-y-2 rounded border border-amber/50 bg-amber/5 p-3">
      <h3 className="text-xs tracking-wider text-muted-foreground uppercase">
        Trigger {chat.trigger.name} · runs as {chat.started_by?.name}
      </h3>
      <pre className="text-sm whitespace-pre-wrap wrap-anywhere">{prompt}</pre>
      <h4 className="text-xs font-bold text-muted-foreground">What happened</h4>
      <pre className="rounded bg-surface-2 p-2 text-xs whitespace-pre-wrap wrap-anywhere">{chat.trigger.what}</pre>
    </section>
  );
}
