import type { ActivityItem, AgentRun, Workflow } from "@/lib/types";

/** A comment marked for the task's agent: who it was written to, and what happened to it. */
export type AgentMessage = NonNullable<ActivityItem["to_agent"]>;

export type AgentHint = "working" | "starting" | "idle" | "nothing_scheduled";

const clean = (name: string) => name.replace(/[[\]\n]/g, " ").slice(0, 200);
const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const agentTokens = (agentId: string) => new RegExp(`@\\[[^\\]\\n]{1,200}\\]\\(agent:${escapeRe(agentId)}\\) ?`, "g");

/** The agent's mention in a comment, like a person's (`@[Name](user:<id>)`). */
export function agentMentionToken(agent: { id: string; name: string }): string {
  return `@[${clean(agent.name)}](agent:${agent.id})`;
}

export function hasAgentMention(body: string, agentId: string): boolean {
  return agentTokens(agentId).test(body);
}

/** The body without the agent's mentions (and the space after each). */
export function removeAgentMentions(body: string, agentId: string): string {
  return body.replace(agentTokens(agentId), "");
}

/** What the task's agent is doing, for the line under the comment box. */
export function agentHint(runs: AgentRun[], workflow: Workflow | undefined): AgentHint {
  if (runs.some((r) => r.status === "running")) return "working";
  if (runs.some((r) => r.status === "queued")) return "starting";
  if (workflow && ["running", "waiting_human", "paused"].includes(workflow.status)) return "idle";
  return "nothing_scheduled";
}

const STAGE_WORD: Record<string, string> = {
  brainstorm: "design",
  design: "design",
  plan: "plan",
  build: "build",
  review: "review",
  done: "finishing",
};

export const stageWord = (stage?: string | null) => (stage ? STAGE_WORD[stage] ?? stage : "work");

export function hintText(hint: AgentHint, agent: string, stage?: string | null): string {
  switch (hint) {
    case "working":
      return `${agent} is working on the ${stageWord(stage)}: it reads this straight away, without stopping.`;
    case "starting":
      return `${agent} is about to start: it gets this as soon as it begins.`;
    case "idle":
      return `${agent} isn't working right now: it gets this when its next run starts, and every later step keeps it in mind.`;
    case "nothing_scheduled":
      return `Nothing is scheduled for ${agent} right now: it gets this if work on the task starts again.`;
  }
}

/** What happened to a message for the agent, for its heading in Activity. */
export function stateText(m: AgentMessage): string {
  switch (m.state) {
    case "waiting":
      return m.error ? `couldn't be delivered (${m.error}): goes to its next run` : "waiting: goes to its next run";
    case "sending":
      return "sending…";
    case "read_while_working":
      return "read while working";
    case "given_at_start":
      return `given at the start of the ${stageWord(m.stage)} run`;
  }
}
