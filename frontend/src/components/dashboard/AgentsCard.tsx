import { Bot } from "lucide-react";

import { RunnerUpdateArrow } from "@/components/agents/RunnerUpdateArrow";
import { Chip, Dot, Empty, type Tone, Widget } from "@/components/dashboard/Widget";
import type { AgentItem } from "@/lib/dashboard";

const STATUS: Record<AgentItem["status"], { label: string; tone: Tone }> = {
  busy: { label: "Working", tone: "cyan" },
  // working in a project outside this view: not counted in Agents working here
  busy_elsewhere: { label: "Working elsewhere", tone: "muted" },
  online: { label: "Idle", tone: "green" },
  offline: { label: "Offline", tone: "muted" },
};

/** Agents in scope: working first, then idle, then offline (the server orders them). */
export function AgentsCard({ agents, isAdmin }: { agents: AgentItem[]; isAdmin: boolean }) {
  return (
    <Widget title="Agents" icon={Bot} more={{ href: isAdmin ? "/admin/agents" : "/settings/agents", label: "Manage" }}>
      {agents.length === 0 ? (
        <Empty>No agents in scope.</Empty>
      ) : (
        <ul className="divide-y divide-line">
          {agents.map((agent) => (
            <li key={agent.id} className="flex min-w-0 items-center gap-2 py-1.5 text-sm">
              <Dot state={agent.status === "busy_elsewhere" ? "busy" : agent.status} />
              <span className={`min-w-0 flex-1 truncate ${agent.status === "offline" ? "text-muted-foreground" : ""}`}>{agent.name}</span>
              <RunnerUpdateArrow runner={agent.runner} ownerId={agent.owner_id} />
              <Chip tone={STATUS[agent.status].tone}>{STATUS[agent.status].label}</Chip>
              <span className="shrink-0 text-xs text-muted-foreground">
                {agent.runs_today} {agent.runs_today === 1 ? "run" : "runs"} today
              </span>
            </li>
          ))}
        </ul>
      )}
    </Widget>
  );
}
