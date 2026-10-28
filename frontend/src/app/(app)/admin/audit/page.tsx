"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { qk } from "@/lib/queries";
import type { AuditEntry, User } from "@/lib/types";

export default function AuditPage() {
  const [action, setAction] = useState("");
  const users = useQuery({ queryKey: qk.users(), queryFn: () => api<User[]>("/api/users") });
  const entries = useQuery({
    queryKey: qk.audit({ action }),
    queryFn: () => api<AuditEntry[]>(`/api/admin/audit?limit=200${action ? `&action=${encodeURIComponent(action)}` : ""}`),
  });
  const names = new Map(users.data?.map((u) => [u.id, u.name]));

  return (
    <div>
      <PageHeader title="Audit log" subtitle="Sign-ins, permission changes and other security-relevant actions." />
      <div className="mb-3 max-w-xs">
        <input
          aria-label="Filter by action"
          placeholder="Filter by action, e.g. auth.login"
          className="w-full rounded border border-line bg-surface-2 px-3 py-2 text-sm"
          value={action}
          onChange={(e) => setAction(e.target.value.trim())}
        />
      </div>
      <div className="card overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs tracking-wider text-muted-foreground uppercase">
            <tr className="border-b border-line">
              <th className="px-3 py-2 font-normal">When</th>
              <th className="px-3 py-2 font-normal">Who</th>
              <th className="px-3 py-2 font-normal">Action</th>
              <th className="px-3 py-2 font-normal">Details</th>
            </tr>
          </thead>
          <tbody>
            {entries.data?.map((e) => (
              <tr key={e.id} className="border-b border-line last:border-0 align-top">
                <td className="px-3 py-2 whitespace-nowrap text-muted-foreground">{new Date(e.created_at).toLocaleString()}</td>
                <td className="px-3 py-2">{e.actor_user_id ? names.get(e.actor_user_id) ?? "unknown" : "—"}</td>
                <td className="px-3 py-2 text-cyan-ink">{e.action}</td>
                <td className="px-3 py-2 text-xs text-muted-foreground">
                  {e.target_type && `${e.target_type} ${e.target_type === "user" && e.target_id ? names.get(e.target_id) ?? "" : ""}`}
                  {Object.keys(e.data ?? {}).length > 0 && <code className="ml-1">{JSON.stringify(e.data)}</code>}
                </td>
              </tr>
            ))}
            {entries.data?.length === 0 && (
              <tr><td colSpan={4} className="px-3 py-6 text-center text-muted-foreground">No entries.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
