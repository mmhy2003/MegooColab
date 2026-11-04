"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { CronEditor } from "@/components/crons/CronEditor";
import { CronReport } from "@/components/crons/CronReport";
import { NotFoundView } from "@/components/shell/NotFound";
import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { api } from "@/lib/api";
import { cronKeys, cronsPath, runOutcome, useCron, useCronRuns } from "@/lib/crons";
import { errorMessage, isNotFound } from "@/lib/errors";
import { useMe } from "@/lib/me";
import { useProject } from "@/lib/project";
import { projectRights } from "@/lib/rights";
import { usePageTitle } from "@/lib/title";

export default function CronPage() {
  const { key, cronId } = useParams<{ key: string; cronId: string }>();
  const router = useRouter();
  const search = useSearchParams();
  const client = useQueryClient();
  const { ask, dialog } = useConfirm();
  const project = useProject(key);
  const { data: me } = useMe();
  const cron = useCron(key, cronId);
  const runs = useCronRuns(key, cronId);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  usePageTitle(cron.data?.name, "Crons");
  if (isNotFound(cron.error)) return <NotFoundView />;
  if (!cron.data || !project.data) return null;
  const c = cron.data;
  const canManage = projectRights(me, project.data).canManage;
  const selected = (runs.data ?? []).find((r) => r.id === search.get("run")) ?? runs.data?.[0];

  const remove = async () => {
    if (!(await ask({ tone: "danger", title: `Delete ${c.name}?`, text: "Its runs and reports go with it.", ok: "Delete cron" }))) return;
    try {
      await api(`${cronsPath(key)}/${c.id}`, { method: "DELETE" });
      await client.invalidateQueries({ queryKey: cronKeys.all });
      router.push(`/projects/${key}/crons`);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div className="space-y-3">
      <header className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1">
          <Link href={`/projects/${key}/crons`} className="text-xs">Crons</Link>
          <h2 className="truncate text-lg font-bold text-cyan-ink">{c.name}</h2>
          <p className="text-sm">
            {c.description} <span className="font-mono text-xs text-muted-foreground">{c.schedule} · {c.timezone}</span>
          </p>
        </div>
        {canManage && (
          <span className="flex flex-wrap gap-2">
            <Button variant="ghost" onClick={() => setEditing(true)}>Edit</Button>
            <Button variant="danger" onClick={remove}>Delete</Button>
          </span>
        )}
      </header>
      <p className="text-sm break-words whitespace-pre-wrap text-muted-foreground">{c.prompt}</p>
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-[320px_minmax(0,1fr)]">
        <ul aria-label="Runs" className="divide-y divide-line rounded border border-line">
          {(runs.data ?? []).length === 0 && <li className="p-3 text-sm text-muted-foreground">No runs yet.</li>}
          {(runs.data ?? []).map((r) => (
            <li key={r.id}>
              <Link href={`/projects/${key}/crons/${c.id}?run=${r.id}`}
                className={`block p-3 text-sm no-underline ${r.id === selected?.id ? "bg-surface-2" : ""}`}>
                <span className="block text-fg">{new Date(r.scheduled_at).toLocaleString()}</span>
                <span className="block text-xs text-muted-foreground">
                  {r.agent ? `${r.agent.name} · ` : ""}{runOutcome(r)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
        {selected && <CronReport projectKey={key} run={selected} />}
      </div>
      {editing && <CronEditor projectKey={key} cron={c} onClose={() => setEditing(false)} />}
      {dialog}
    </div>
  );
}
