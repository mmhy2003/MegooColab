"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { BoardDialog } from "@/components/chats/BoardDialog";
import { ChatComposer } from "@/components/chats/ChatComposer";
import { EndChatButton } from "@/components/chats/EndChatButton";
import { RoundDivider } from "@/components/chats/RoundDivider";
import { ActivityThread } from "@/components/task/ActivityThread";
import { DocumentView } from "@/components/workflow/DocumentView";
import { useAgentRuns } from "@/lib/agents";
import { api } from "@/lib/api";
import { latestRound, stateText, useChat, type Chat, type ChatRound } from "@/lib/chats";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import { useRecordTitle } from "@/lib/title";
import type { ActivityItem } from "@/lib/types";
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

/** A chat: its rounds as one conversation, the progress of the latest, and the message box at the bottom. */
export function ChatView({ chatId }: { chatId: string }) {
  const chat = useChat(chatId);
  useRecordTitle(chat.data?.title);
  const latest = chat.data ? latestRound(chat.data) : undefined;
  const runs = useAgentRuns(latest?.key ?? "");
  const agentRunning = (runs.data ?? []).some((r) => r.status === "running");
  if (chat.error) return <p role="alert" className="card p-4 text-sm text-pink">{errorMessage(chat.error)}</p>;
  if (!chat.data) return <p className="card p-4 text-sm text-muted-foreground">Loading…</p>;
  const c = chat.data;
  const pending = c.can_act ? c.rounds.find((r) => r.board === "pending") : undefined;
  return (
    <div className="card flex min-h-[60vh] flex-col">
      <header className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
        <h2 className="text-base font-bold">{c.title}</h2>
        <span className="rounded border border-cyan px-1.5 text-xs text-cyan-ink">{c.project_key}</span>
        {c.agent && (
          <span className="rounded border border-line px-1.5 text-xs text-muted-foreground">
            {c.agent.name} · {c.agent.program === "codex" ? "Codex" : "Claude Code"}
          </span>
        )}
        <span className="text-xs text-muted-foreground">{stateText(c)}</span>
        <div className="ml-auto flex items-center gap-2">
          <ChatProgress round={latest} />
          {c.can_act && c.status === "open" && <EndChatButton chat={c} agentRunning={agentRunning} />}
        </div>
      </header>
      <div className="flex-1 space-y-2 overflow-y-auto px-4 py-3">
        {c.rounds.map((r) => (
          <div key={r.key}>
            {c.rounds.length > 1 && <RoundDivider round={r} canEdit={c.can_act && r === latest} />}
            <RoundThread chat={c} round={r} />
          </div>
        ))}
      </div>
      <div className="sticky bottom-0 border-t border-line bg-surface px-4 py-3">
        <ChatComposer chat={c} agentRunning={agentRunning} />
      </div>
      {pending && <BoardDialog key={pending.key} chat={c} round={pending} />}
    </div>
  );
}
