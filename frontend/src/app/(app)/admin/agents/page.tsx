"use client";

import { useQuery } from "@tanstack/react-query";

import { AdminOnly } from "@/components/admin/AdminOnly";
import { AgentStatusDot } from "@/components/agents/AgentStatusDot";
import { RunnerUpdateArrow } from "@/components/agents/RunnerUpdateArrow";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { PROGRAM_LABEL } from "@/lib/agents";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import type { AdminAgent } from "@/lib/types";

function AdminAgentsPageContent() {
  const agents = useQuery({ queryKey: qk.adminAgents(), queryFn: () => api<AdminAgent[]>("/api/admin/agents") });
  return (
    <div>
      <PageHeader title="Agents" subtitle="Every agent registered in this workspace." />
      {agents.error && <p role="alert" className="mb-2 text-sm text-pink">{errorMessage(agents.error)}</p>}
      <div className="card overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs tracking-wider text-muted-foreground uppercase">
            <tr className="border-b border-line">
              <th className="px-3 py-2 font-normal">Owner</th>
              <th className="px-3 py-2 font-normal">Agent</th>
              <th className="px-3 py-2 font-normal">Program</th>
              <th className="px-3 py-2 font-normal">Status</th>
              <th className="px-3 py-2 font-normal">Current run</th>
            </tr>
          </thead>
          <tbody>
            {agents.data?.map((a) => (
              <tr key={a.id} className="border-b border-line last:border-0">
                <td className="px-3 py-2">{a.owner.name}</td>
                <td className="px-3 py-2">{a.name}</td>
                <td className="px-3 py-2 text-muted-foreground">{PROGRAM_LABEL[a.program]}</td>
                <td className="px-3 py-2">
                  <span className="inline-flex items-center gap-1.5">
                    <AgentStatusDot status={a.status} />
                    {a.machine && <span className="text-xs text-muted-foreground">on {a.machine.name}</span>}
                    <RunnerUpdateArrow runner={a.runner} ownerId={a.owner.id} />
                  </span>
                </td>
                <td className="px-3 py-2 text-muted-foreground">{runLabel(a.current_run)}</td>
              </tr>
            ))}
            {agents.data?.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-muted-foreground">No agents yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function runLabel(run: AdminAgent["current_run"]): string {
  const key = run && typeof run.task_key === "string" ? run.task_key : null;
  return key ?? "—";
}

export default function AdminAgentsPage() {
  return (
    <AdminOnly>
      <AdminAgentsPageContent />
    </AdminOnly>
  );
}
