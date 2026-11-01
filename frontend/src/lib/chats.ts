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

export function waitingOnMe(chats: Chat[] | undefined): number {
  return (chats ?? []).filter((c) => c.can_act && WAITING.includes(c.state)).length;
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
    case "new_round":
      return "Starts a new round: the agent talks it through, then design, plan, build and finish again.";
    case "closed":
      return "This chat has ended.";
  }
}
