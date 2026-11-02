"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useRef } from "react";

import { BoardDialog } from "@/components/chats/BoardDialog";
import { ChatComposer } from "@/components/chats/ChatComposer";
import { EndChatButton } from "@/components/chats/EndChatButton";
import { ImageGallery } from "@/components/images/ImageGallery";
import { RoundDivider } from "@/components/chats/RoundDivider";
import { ActivityThread } from "@/components/task/ActivityThread";
import { JumpButtons } from "@/components/task/JumpButtons";
import { DocumentView } from "@/components/workflow/DocumentView";
import { PROGRAM_LABEL, useAgentRuns } from "@/lib/agents";
import { api } from "@/lib/api";
import { latestRound, stateText, useChat, WAITING, type Chat, type ChatRound } from "@/lib/chats";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import { useRecordTitle } from "@/lib/title";
import { useRecordTrail } from "@/lib/trail";
import type { ActivityItem, AgentProgram } from "@/lib/types";
import { useWorkflow } from "@/lib/workflow";

const PROGRESS = ["Talk", "Design", "Plan", "Build", "Finish"] as const;
const STEP_OF: Record<string, number> = { brainstorm: 0, design: 1, plan: 2, build: 3, review: 3, done: 4 };

/** Talk · Design · Plan · Build · Finish for the latest round: the steps it has passed, and the one it is on. */
export function ChatProgress({ round }: { round?: ChatRound }) {
  const finished = round?.status === "finished";
  const at = finished ? PROGRESS.length : STEP_OF[round?.stage ?? "brainstorm"] ?? 0;
  return (
    <ol aria-label="Progress" className="flex flex-wrap gap-1">
      {PROGRESS.map((label, i) => (
        <li
          key={label}
          aria-current={i === at ? "step" : undefined}
          className={`rounded border px-2 py-0.5 text-[11px] ${
            i < at ? "border-green/40 text-green" : i === at ? "border-cyan text-cyan-ink" : "border-line text-muted-foreground"
          }`}
        >
          {label}
        </li>
      ))}
    </ol>
  );
}

/** One round's conversation: what was said and done, its questions, and its design and plan with their buttons. */
function RoundThread({ chat, round }: { chat: Chat; round: ChatRound }) {
  const activity = useQuery({
    queryKey: qk.activity(round.key),
    queryFn: () => api<ActivityItem[]>(`/api/tasks/${round.key}/activity?limit=200`),
  });
  const workflow = useWorkflow(round.key);
  const agentNames = useMemo(() => new Map(chat.agent ? [[chat.agent.id, chat.agent.name]] : []), [chat.agent]);
  const docs = workflow.data?.documents ?? [];
  const readOnly = !chat.can_act;
  return (
    <div className="space-y-4">
      {(round.images ?? []).length > 0 && (
        <section aria-label="Images with the first message">
          <h3 className="text-xs tracking-wider text-muted-foreground uppercase">Images with the first message</h3>
          <ImageGallery images={round.images ?? []} />
        </section>
      )}
      <ActivityThread
        items={activity.data ?? []}
        columnNames={new Map()}
        userNames={new Map()}
        agentNames={agentNames}
        taskKey={round.key}
        canAct={workflow.data?.can_act === true && chat.status === "open"}
        readOnly={readOnly}
      />
      {(["design", "plan"] as const).map(
        (kind) =>
          docs.some((d) => d.kind === kind) && (
            <section key={kind} aria-label={kind === "design" ? "Design" : "Plan"} className="rounded border border-violet/50 bg-violet/5 p-3">
              <h3 className="mb-2 text-xs tracking-wider text-muted-foreground uppercase">{kind === "design" ? "Design" : "Plan"}</h3>
              <DocumentView taskKey={round.key} kind={kind} disabled={readOnly || chat.status !== "open"} />
            </section>
          ),
      )}
    </div>
  );
}

/**
 * A chat: its rounds as one conversation, the progress of the latest, and the message box at the bottom. It fills
 * the height it is given: the header stays at the top and the message box at the bottom, only the conversation
 * scrolls between them, with a task's corner buttons (back to top, the latest, what waits on the viewer).
 */
export function ChatView({ chatId }: { chatId: string }) {
  const chat = useChat(chatId);
  useRecordTitle(chat.data?.title);
  useRecordTrail([{ label: "Chats", href: "/chats" }, { label: chat.data?.title ?? null }]);
  const latest = chat.data ? latestRound(chat.data) : undefined;
  const runs = useAgentRuns(latest?.key ?? "");
  const agentRunning = (runs.data ?? []).some((r) => r.status === "running");
  // the latest round's thread is the one that grows: what the corner buttons follow and count (the same query
  // RoundThread reads)
  const activity = useQuery({
    queryKey: qk.activity(latest?.key ?? ""),
    queryFn: () => api<ActivityItem[]>(`/api/tasks/${latest?.key}/activity?limit=200`),
    enabled: !!latest,
  });
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const jumpRef = useRef<(() => void) | null>(null);
  if (chat.error) return <p role="alert" className="card p-4 text-sm text-pink">{errorMessage(chat.error)}</p>;
  if (!chat.data) return <p className="card p-4 text-sm text-muted-foreground">Loading…</p>;
  const c = chat.data;
  const pending = c.can_act ? c.rounds.find((r) => r.board === "pending") : undefined;
  // what waits on the viewer goes there, as the corner's "waiting on you" does; an escalation has nothing in the
  // conversation to go to
  const goesToWaiting = c.can_act && WAITING.includes(c.state) && c.state !== "escalation";
  return (
    <div className="card flex h-full min-h-0 flex-col">
      <header className="shrink-0 space-y-2 border-b border-line px-4 py-3">
        <div className="flex items-start gap-3">
          {/* a long title wraps to two lines, then is cut; the whole of it shows on hover (and in the tab's title) */}
          <h2 title={c.title} className="line-clamp-2 min-w-0 flex-1 text-base font-bold break-words">
            {c.title}
          </h2>
          {c.can_act && c.status === "open" && <EndChatButton chat={c} agentRunning={agentRunning} />}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded border border-cyan px-1.5 text-cyan-ink">{c.project_key}</span>
          {c.agent && (
            <span className="rounded border border-line px-1.5 text-muted-foreground">
              {c.agent.name} · {PROGRAM_LABEL[c.agent.program as AgentProgram] ?? c.agent.program}
            </span>
          )}
          {goesToWaiting ? (
            <button
              type="button"
              onClick={() => jumpRef.current?.()}
              className="rounded-full border border-amber/50 bg-amber/10 px-2 text-amber hover:border-amber"
            >
              <span aria-hidden>● </span>
              {stateText(c)}
            </button>
          ) : (
            <span className="text-muted-foreground">{stateText(c)}</span>
          )}
          <div className="ml-auto">
            <ChatProgress round={latest} />
          </div>
        </div>
      </header>
      <div className="relative min-h-0 flex-1">
        <div ref={scrollRef} data-thread className="h-full overflow-y-auto px-4 py-3">
          <div className="space-y-2">
            {c.rounds.map((r) => (
              <div key={r.key}>
                {c.rounds.length > 1 && <RoundDivider round={r} canEdit={c.can_act && r === latest} />}
                <RoundThread chat={c} round={r} />
              </div>
            ))}
          </div>
        </div>
        {activity.data && <JumpButtons key={chatId} scrollRef={scrollRef} activity={activity.data} startFollowing jumpRef={jumpRef} />}
      </div>
      <div className="shrink-0 border-t border-line bg-surface px-4 py-3">
        <ChatComposer chat={c} agentRunning={agentRunning} />
      </div>
      {pending && <BoardDialog key={pending.key} chat={c} round={pending} />}
    </div>
  );
}
