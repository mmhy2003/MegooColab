"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input, Textarea } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { canManage, useMe } from "@/lib/me";
import { qk } from "@/lib/queries";
import type { Team } from "@/lib/types";
import { usePageTitle } from "@/lib/title";

function NewTeamDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <Dialog open title="New team" onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            const team = await api<Team>("/api/teams", { method: "POST", json: { name, description } });
            await client.invalidateQueries({ queryKey: qk.teams() });
            router.push(`/teams/${team.id}`);
          } catch (err) {
            setError(errorMessage(err));
          }
        }}
      >
        <Input label="Name" required value={name} onChange={(e) => setName(e.target.value)} />
        <Textarea label="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
        {error && <p role="alert" className="text-sm text-pink">{error}</p>}
        <Button type="submit">Create team</Button>
      </form>
    </Dialog>
  );
}

export default function TeamsPage() {
  usePageTitle("Teams");
  const { data: me } = useMe();
  const [creating, setCreating] = useState(false);
  const teams = useQuery({ queryKey: qk.teams(), queryFn: () => api<Team[]>("/api/teams") });
  return (
    <div>
      <PageHeader
        title="Teams"
        subtitle="Teams own projects; membership decides who sees what."
        actions={
          canManage(me) && (
            <Button onClick={() => setCreating(true)}>
              <Plus size={14} aria-hidden /> New team
            </Button>
          )
        }
      />
      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {teams.data?.map((t) => (
          <Link key={t.id} href={`/teams/${t.id}`} className="card block p-4 text-fg no-underline hover:glow-box">
            <h2 className="text-sm text-cyan-ink">{t.name}</h2>
            {t.description && <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{t.description}</p>}
            <p className="mt-3 text-xs text-muted-foreground">
              {t.member_count} members · {t.project_count} projects
            </p>
          </Link>
        ))}
        {teams.data?.length === 0 && <p className="text-sm text-muted-foreground">No teams yet.</p>}
      </div>
      {creating && <NewTeamDialog onClose={() => setCreating(false)} />}
    </div>
  );
}
