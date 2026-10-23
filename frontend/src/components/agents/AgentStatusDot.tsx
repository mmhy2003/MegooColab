import { asAgentStatus, type AgentStatus } from "@/lib/agents";

const STYLE: Record<AgentStatus, { dot: string; text: string; label: string }> = {
  online: { dot: "bg-green", text: "text-green-ink", label: "Online" },
  busy: { dot: "bg-cyan animate-pulse", text: "text-cyan-ink", label: "Busy" },
  offline: { dot: "bg-muted", text: "text-muted", label: "Offline" },
};

/** Status is always shown as text next to the dot, never by color alone. */
export function AgentStatusDot({ status }: { status: string }) {
  const s = STYLE[asAgentStatus(status)];
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs ${s.text}`}>
      <span aria-hidden className={`inline-block h-2 w-2 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}
