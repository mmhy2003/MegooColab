"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { hubKeys, type HubTool } from "@/lib/hub";
import { useMe } from "@/lib/me";
import { qk } from "@/lib/queries";
import type { Team, User } from "@/lib/types";

type Person = { id: string; name: string };

/** Who sees a tool: teams you belong to, people, or everyone. Its secrets never go with it. */
export function ShareEditor({ tool }: { tool: HubTool }) {
  const client = useQueryClient();
  const me = useMe().data;
  const sharing = tool.sharing ?? { teams: [], users: [], everyone: false };
  const [teams, setTeams] = useState<string[]>(sharing.teams.map((t) => t.id));
  const [people, setPeople] = useState<Person[]>(sharing.users);
  const [everyone, setEveryone] = useState(sharing.everyone);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const allTeams = useQuery({ queryKey: qk.teams(), queryFn: () => api<Team[]>("/api/teams") });
  const found = useQuery({
    queryKey: qk.users(q.trim()),
    queryFn: () => api<User[]>(`/api/users?${new URLSearchParams({ q: q.trim(), status: "active" })}`),
    enabled: q.trim().length > 0,
  });
  const myTeams = (allTeams.data ?? []).filter((t) => t.is_member || me?.role === "admin" || teams.includes(t.id));
  const candidates = (found.data ?? []).filter((u) => u.id !== me?.id && !people.some((p) => p.id === u.id));
  const nothing = teams.length === 0 && people.length === 0 && !everyone;

  const acknowledge = async (location: string) => {
    setError(null);
    try {
      const spec = { ...tool.spec!, acknowledged: [...(tool.spec?.acknowledged ?? []), location] };
      await api(`/api/hub/tools/${tool.id}`, { method: "PATCH", json: { spec } });
      await client.invalidateQueries({ queryKey: hubKeys.all });
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div className="space-y-4">
      {tool.flagged.length > 0 && (
        <div className="rounded border border-amber p-3 text-sm">
          <p>These values look like keys. Mark them secret in the setup, or confirm they aren&apos;t:</p>
          <ul className="mt-2 space-y-1">
            {tool.flagged.map((f) => (
              <li key={f} className="flex items-center gap-2">
                <code className="text-xs">{f}</code>
                <Button variant="ghost" aria-label={`Not a secret: ${f}`} onClick={() => acknowledge(f)}>Not a secret</Button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <fieldset className="space-y-1">
        <legend className="text-xs tracking-wider text-muted-foreground uppercase">Teams</legend>
        {myTeams.length === 0 && <p className="text-sm text-muted-foreground">You aren&apos;t in any team.</p>}
        {myTeams.map((t) => (
          <label key={t.id} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={teams.includes(t.id)}
              onChange={(e) => setTeams(e.target.checked ? [...teams, t.id] : teams.filter((x) => x !== t.id))}
            />
            {t.name}
          </label>
        ))}
      </fieldset>
      <div className="space-y-2">
        <Input label="Find people" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name or email" maxLength={200} />
        {candidates.length > 0 && (
          <ul className="space-y-1">
            {candidates.slice(0, 8).map((u) => (
              <li key={u.id}>
                <Button variant="ghost" aria-label={`Add ${u.name}`} onClick={() => setPeople([...people, { id: u.id, name: u.name }])}>
                  + {u.name}
                </Button>
              </li>
            ))}
          </ul>
        )}
        {people.length > 0 && (
          <ul className="flex flex-wrap gap-2">
            {people.map((p) => (
              <li key={p.id} className="flex items-center gap-1 rounded border border-line px-2 py-0.5 text-sm">
                {p.name}
                <button type="button" aria-label={`Remove ${p.name}`} onClick={() => setPeople(people.filter((x) => x.id !== p.id))}>
                  <X size={12} aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={everyone} onChange={(e) => setEveryone(e.target.checked)} />
        Everyone on MegooColab
      </label>
      {nothing && <p className="text-sm text-muted-foreground">Only me: nobody else sees it.</p>}
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      {saved && <p role="status" className="text-sm text-green-ink">Saved.</p>}
      <Button
        disabled={tool.flagged.length > 0 && !nothing}
        onClick={async () => {
          setError(null);
          setSaved(false);
          try {
            await api(`/api/hub/tools/${tool.id}/sharing`, {
              method: "PUT",
              json: { teams, users: people.map((p) => p.id), everyone },
            });
            setSaved(true);
            await client.invalidateQueries({ queryKey: hubKeys.all });
          } catch (err) {
            setError(errorMessage(err));
          }
        }}
      >
        Share
      </Button>
    </div>
  );
}
