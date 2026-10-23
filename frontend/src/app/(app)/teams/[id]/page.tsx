"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { AgentStatusDot } from "@/components/agents/AgentStatusDot";
import { PROGRAM_LABEL } from "@/lib/agents";
import { MemberPicker } from "@/components/team/MemberPicker";
import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useMe } from "@/lib/me";
import { qk } from "@/lib/queries";
import type { TeamDetail, User } from "@/lib/types";

export default function TeamPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const client = useQueryClient();
  const { data: me } = useMe();
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const team = useQuery({ queryKey: qk.team(id), queryFn: () => api<TeamDetail>(`/api/teams/${id}`) });
  const users = useQuery({ queryKey: qk.users(), queryFn: () => api<User[]>("/api/users"), enabled: editing });

  if (team.error) return <p className="text-sm text-pink">{errorMessage(team.error)}</p>;
  if (!team.data) return null;
  const t = team.data;
  const isMember = t.members.some((m) => m.id === me?.id);
  const canEdit = me?.role === "admin" || (me?.role === "manager" && isMember);

  return (
    <div className="space-y-6">
      <PageHeader
        title={t.name}
        subtitle={t.description || undefined}
        actions={
          canEdit && (
            <>
              <Button variant="ghost" onClick={() => setEditing(true)}>Edit members</Button>
              <Button
                variant="danger"
                onClick={async () => {
                  if (!confirm(`Delete team ${t.name}?`)) return;
                  try {
                    await api(`/api/teams/${t.id}`, { method: "DELETE" });
                    await client.invalidateQueries({ queryKey: qk.teams() });
                    router.push("/teams");
                  } catch (err) {
                    setError(errorMessage(err));
                  }
                }}
              >
                Delete
              </Button>
            </>
          )
        }
      />
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      <section>
        <h2 className="mb-2 text-xs tracking-widest text-muted uppercase">Members ({t.members.length})</h2>
        <ul className="card divide-y divide-line">
          {t.members.map((m) => (
            <li key={m.id} className="flex items-center gap-2 px-3 py-2 text-sm">
              <Avatar name={m.name} /> <span className="flex-1">{m.name}</span>
              <Badge>{m.role}</Badge>
            </li>
          ))}
          {t.members.length === 0 && <li className="px-3 py-4 text-sm text-muted">No members yet.</li>}
        </ul>
      </section>
      <section>
        <h2 className="mb-2 text-xs tracking-widest text-muted uppercase">Projects ({t.projects.length})</h2>
        <ul className="flex flex-wrap gap-2">
          {t.projects.map((p) => (
            <li key={p.id}>
              <Link href={`/projects/${p.key}/board`} className="card inline-block px-3 py-2 text-sm no-underline hover:glow-box">
                <span className="text-muted">{p.key}</span> {p.name}
              </Link>
            </li>
          ))}
          {t.projects.length === 0 && <li className="text-sm text-muted">No projects yet.</li>}
        </ul>
      </section>
      <section>
        <h2 className="mb-2 text-xs tracking-widest text-muted uppercase">Agents ({t.agents.length})</h2>
        <ul className="card divide-y divide-line">
          {t.agents.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
              <span className="flex-1">{a.name}</span>
              <span className="text-muted">{a.owner.name}</span>
              <Badge>{PROGRAM_LABEL[a.program]}</Badge>
              <AgentStatusDot status={a.status} />
            </li>
          ))}
          {t.agents.length === 0 && <li className="px-3 py-4 text-sm text-muted">No agents yet.</li>}
        </ul>
      </section>
      {editing && users.data && (
        <Dialog open title={`Members of ${t.name}`} onClose={() => setEditing(false)}>
          <MemberPicker
            users={users.data}
            selected={t.members.map((m) => m.id)}
            onSave={async (ids) => {
              try {
                await api(`/api/teams/${t.id}/members`, { method: "PUT", json: { user_ids: ids } });
                await client.invalidateQueries({ queryKey: qk.team(id) });
                await client.invalidateQueries({ queryKey: qk.teams() });
                setEditing(false);
              } catch (err) {
                setError(errorMessage(err));
              }
            }}
          />
        </Dialog>
      )}
    </div>
  );
}
