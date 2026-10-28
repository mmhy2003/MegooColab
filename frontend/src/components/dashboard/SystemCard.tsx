import { HeartPulse } from "lucide-react";

import { Dot, Widget } from "@/components/dashboard/Widget";
import type { SystemOut } from "@/lib/dashboard";

const JOBS_WAITING_LIMIT = 50;
const JOB_WAIT_LIMIT_SECONDS = 300;
const MEMORY_STALE_HOURS = 26;

export type SystemLine = { label: string; value: string; attention: boolean };

/** The six status lines, each amber when it needs an admin's attention. */
export function systemLines(s: SystemOut, now: Date): SystemLine[] {
  const memoryAt = s.memory_last_at ? new Date(s.memory_last_at) : null;
  const memoryStale = !memoryAt || now.getTime() - memoryAt.getTime() > MEMORY_STALE_HOURS * 3_600_000;
  return [
    { label: "Runners connected", value: `${s.runners} connected`, attention: s.runners === 0 && s.agents_exist },
    {
      label: "Background jobs",
      value: `${s.jobs_waiting} waiting`,
      attention: s.jobs_waiting > JOBS_WAITING_LIMIT || (s.oldest_job_seconds ?? 0) > JOB_WAIT_LIMIT_SECONDS,
    },
    {
      label: "Search index",
      value: s.search_available ? `Available · ${s.search_documents ?? 0} items` : "Unavailable",
      attention: !s.search_available,
    },
    {
      label: "AI provider",
      value: s.ai_configured ? `OK · ${s.ai_jobs_today} jobs today` : "Not configured",
      attention: !s.ai_configured || s.ai_failed_today > 0,
    },
    {
      label: "Memory",
      value: memoryAt ? `last learned ${memoryAt.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false })}` : "never",
      attention: s.memory_last_failed || memoryStale,
    },
    { label: "Rate limits hit", value: `${s.rate_limits_24h} in 24 h`, attention: s.rate_limits_24h > 0 },
  ];
}

/** System status (admins only): green when fine, amber when it needs attention. */
export function SystemCard({ system }: { system: SystemOut }) {
  return (
    <Widget title="System" icon={HeartPulse} tag="admins only">
      <ul className="grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-2">
        {systemLines(system, new Date()).map((line) => (
          <li key={line.label} className="flex min-w-0 items-center gap-1.5" data-attention={line.attention}>
            <Dot state={line.attention ? "attention" : "online"} />
            <span className="truncate">{line.label}</span>
            <span className="ml-auto shrink-0 font-mono text-xs text-muted-foreground">{line.value}</span>
          </li>
        ))}
      </ul>
    </Widget>
  );
}
