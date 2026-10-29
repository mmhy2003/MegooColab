"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useMe } from "@/lib/me";
import { useTeams } from "@/lib/project";
import { qk } from "@/lib/queries";
import { teamChoices } from "@/lib/rights";
import type { Project } from "@/lib/types";

export default function NewProjectPage() {
  const router = useRouter();
  const client = useQueryClient();
  const teams = useTeams();
  const { data: me } = useMe();
  const choices = teamChoices(teams.data ?? [], me, []);
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [teamIds, setTeamIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="max-w-xl">
      <PageHeader title="New project" />
      <form
        className="card space-y-4 p-4"
        onSubmit={async (e) => {
          e.preventDefault();
          if (teamIds.length === 0) return setError("Pick at least one team.");
          try {
            const p = await api<Project>("/api/projects", { method: "POST", json: { key, name, description, team_ids: teamIds } });
            await client.invalidateQueries({ queryKey: qk.projects() });
            router.push(`/projects/${p.key}/board`);
          } catch (err) {
            setError(errorMessage(err));
          }
        }}
      >
        <Input label="Name" required value={name} onChange={(e) => setName(e.target.value)} />
        <Input
          label="Key (2–10 letters/digits, starts with a letter; used in task IDs like PAY-12)"
          required
          pattern="[A-Z][A-Z0-9]{1,9}"
          value={key}
          onChange={(e) => setKey(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 10))}
        />
        <Textarea label="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
        <fieldset>
          <legend className="mb-1 text-xs tracking-wider text-muted-foreground uppercase">Teams</legend>
          <div className="flex flex-wrap gap-3">
            {choices.map((t) => (
              <label key={t.id} className="flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={teamIds.includes(t.id)}
                  onChange={(e) => setTeamIds(e.target.checked ? [...teamIds, t.id] : teamIds.filter((x) => x !== t.id))}
                />
                {t.name}
              </label>
            ))}
            {teams.data && me && choices.length === 0 && <p className="text-sm text-muted-foreground">Create a team first.</p>}
          </div>
        </fieldset>
        {error && <p role="alert" className="text-sm text-pink">{error}</p>}
        <Button type="submit">Create project</Button>
      </form>
    </div>
  );
}
