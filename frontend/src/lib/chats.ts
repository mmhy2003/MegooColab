import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";

type S = components["schemas"];
export type Chat = S["ChatOut"];
export type ChatRound = S["RoundOut"];
export type ChatState = Chat["state"];
export type ChatIntent = NonNullable<Chat["intent"]>;
export type BoardDefaults = S["BoardDefaults"];

/** The states in which a chat waits on the people who direct its agent. */
export const WAITING: ChatState[] = ["question", "design_approval", "plan_approval", "escalation"];

export const chatKeys = {
  list: (project?: string) => ["chats", project ?? ""] as const,
  one: (id: string) => ["chats", "one", id] as const,
};

/** Chats the viewer can see (one project's, or all), waiting on them first. */
export function useChats(project?: string) {
  const qs = project ? `?project=${encodeURIComponent(project)}` : "";
  return useQuery({ queryKey: chatKeys.list(project), queryFn: () => api<Chat[]>(`/api/chats${qs}`) });
}

export function useChat(id: string | undefined) {
  return useQuery({ queryKey: chatKeys.one(id ?? ""), queryFn: () => api<Chat>(`/api/chats/${id}`), enabled: !!id });
}

/** How many open chats wait on the viewer: one cheap count, for the sidebar badge. */
export function useChatsWaiting() {
  return useQuery({ queryKey: ["chats", "count"], queryFn: () => api<{ waiting: number }>("/api/chats/count") });
}

export function waitingOnMe(chats: Chat[] | undefined): number {
  return (chats ?? []).filter((c) => c.can_act && WAITING.includes(c.state)).length;
}

/** Where a chat stands, for its mark in the list and the filters: waiting on a person, its agent at work, the next
 * message the person's to write, its agent's runner away, or over. */
export type ChatGroup = "needs_you" | "working" | "open" | "offline" | "ended";

const GROUP: Record<ChatState, ChatGroup> = {
  question: "needs_you", design_approval: "needs_you", plan_approval: "needs_you", escalation: "needs_you",
  human_code_review: "needs_you",
  building: "working", in_review: "working", merging: "working", working: "working",
  talking: "open", reply: "open", finished: "open",
  offline: "offline",
  ended: "ended",
};

export function chatGroup(chat: Pick<Chat, "state" | "status">): ChatGroup {
  return chat.status === "ended" ? "ended" : GROUP[chat.state];
}

/** The filters over the chat list: Active is everything not ended (the default); Open takes offline chats too. */
export type ChatFilter = "all" | "active" | "needs_you" | "working" | "open" | "ended";
export const CHAT_FILTERS: { value: ChatFilter; label: string; empty: string }[] = [
  { value: "all", label: "All", empty: "No chats yet." },
  { value: "active", label: "Active", empty: "No active chats." },
  { value: "needs_you", label: "Needs you", empty: "Nothing needs you." },
  { value: "working", label: "Working", empty: "No agent is working." },
  { value: "open", label: "Open", empty: "No open chats." },
  { value: "ended", label: "Ended", empty: "No ended chats." },
];

export function inFilter(chat: Pick<Chat, "state" | "status">, filter: ChatFilter): boolean {
  const group = chatGroup(chat);
  switch (filter) {
    case "all":
      return true;
    case "active":
      return group !== "ended";
    case "open":
      return group === "open" || group === "offline";
    default:
      return group === filter;
  }
}

export const latestRound = (chat: Chat): ChatRound | undefined => chat.rounds[chat.rounds.length - 1];

function prNumber(url?: string | null): string | null {
  const m = url ? /(\d+)\/?$/.exec(url) : null;
  return m ? m[1] : null;
}

/** What a chat's latest round is doing, from the few fields both a chat and the dashboard's brief carry. */
export type StateBits = {
  state: ChatState;
  current_step?: number | null;
  steps_total?: number | null;
  pr_url?: string | null;
  finish_outcome?: string | null;
  agent_name?: string | null;
};

/** What a chat is doing, in a few words (the chat list). */
export function stateText(chat: Chat): string {
  const r = latestRound(chat);
  return chatStateText({
    state: chat.state, current_step: r?.current_step, steps_total: r?.steps_total, pr_url: r?.pr_url,
    finish_outcome: r?.finish_outcome, agent_name: chat.agent?.name,
  });
}

/** What a chat is doing, in a few words (the chat list, the dashboard). */
export function chatStateText(r: StateBits): string {
  const pr = prNumber(r.pr_url);
  switch (r.state) {
    case "talking":
      return "talking";
    case "question":
      return "waiting: answer the agent's question";
    case "design_approval":
      return "waiting: approve the design";
    case "plan_approval":
      return "waiting: approve the plan";
    case "building":
      return r.current_step && r.steps_total ? `building step ${r.current_step} of ${r.steps_total}` : "building";
    case "in_review":
      return "in review";
    case "human_code_review":
      return pr ? `in code review · PR #${pr}` : "in code review";
    case "merging":
      return pr ? `merging · PR #${pr}` : "merging";
    case "escalation":
      return "waiting: decide the escalation";
    case "offline":
      return `offline — starts when ${r.agent_name ? `${r.agent_name}'s` : "its"} runner connects`;
    case "finished":
      if (r.finish_outcome === "pr_opened") return pr ? `finished · PR #${pr}` : "finished · pull request";
      if (r.finish_outcome === "merged_local") return "finished · merged";
      return "finished";
    case "ended":
      return "ended";
    case "working":
      return "working";
    case "reply":
      return "waiting for your reply";
  }
}

/** What sending a message does now, for the line under the chat's message box. */
export function intentText(chat: Chat, agentRunning: boolean): string {
  const agent = chat.agent?.name ?? "The agent";
  const r = latestRound(chat);
  switch (chat.intent ?? "closed") {
    case "answer":
      return `Your message answers ${agent}'s question.`;
    case "changes":
      return `Your message asks ${agent} to change the ${r?.needs === "design_approval" ? "design" : "plan"}. Approve stays on the card.`;
    case "tell":
      return agentRunning
        ? `${agent} reads this straight away, without stopping.`
        : `${agent} gets this when its next run starts.`;
    case "restart":
      return `Your message starts ${agent} again.`;
    case "retry":
      return `Retry with your message: ${agent} starts again and reads it.`;
    case "new_round":
      return "Starts a new round: the agent talks it through, then design, plan, build and finish again.";
    case "turn":
      return `${agent} starts working on your message.`;
    case "closed":
      return "This chat has ended.";
  }
}
