"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { NotFoundView } from "@/components/shell/NotFound";
import { FiringList } from "@/components/triggers/FiringList";
import { TriggerEditor } from "@/components/triggers/TriggerEditor";
import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { api } from "@/lib/api";
import { useCrons } from "@/lib/crons";
import { errorMessage, isNotFound } from "@/lib/errors";
import { useMe } from "@/lib/me";
import { useColumns, useLabels, useProject } from "@/lib/project";
import { projectRights } from "@/lib/rights";
import { usePageTitle } from "@/lib/title";
import { BROKEN_TEXT, eventInfo, filterText, triggerKeys, triggersPath, useTrigger } from "@/lib/triggers";

export default function TriggerPage() {
  const { key, triggerId } = useParams<{ key: string; triggerId: string }>();
  const router = useRouter();
  const client = useQueryClient();
  const { ask, dialog } = useConfirm();
  const project = useProject(key);
  const { data: me } = useMe();
  const trigger = useTrigger(key, triggerId);
  const columns = useColumns(key);
  const labels = useLabels(key);
  const crons = useCrons(key);
  const names = useMemo(() => ({
    columns: new Map((columns.data ?? []).map((c) => [c.id, c.name])),
    labels: new Map((labels.data ?? []).map((l) => [l.id, l.name])),
    crons: new Map((crons.data ?? []).map((c) => [c.id, c.name])),
  }), [columns.data, labels.data, crons.data]);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  usePageTitle(trigger.data?.name, "Triggers");
  if (isNotFound(trigger.error)) return <NotFoundView />;
  if (!trigger.data || !project.data) return null;
  const t = trigger.data;
  const canManage = projectRights(me, project.data).canManage;
  const info = eventInfo(t.event);
  const filter = filterText(t, names);

  const run = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
      await client.invalidateQueries({ queryKey: triggerKeys.all });
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  const post = (action: "pause" | "resume" | "try") =>
    run(() => api(`${triggersPath(key)}/${t.id}/${action}`, { method: "POST" }));

  const remove = async () => {
    if (!(await ask({
      tone: "danger", title: `Delete ${t.name}?`, text: "Its firings go with it. The chats it started stay.", ok: "Delete trigger",
    }))) return;
    try {
      await api(`${triggersPath(key)}/${t.id}`, { method: "DELETE" });
      await client.invalidateQueries({ queryKey: triggerKeys.all });
      router.push(`/projects/${key}/triggers`);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div className="space-y-3">
      <header className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1">
          <Link href={`/projects/${key}/triggers`} className="text-xs">Triggers</Link>
          <h2 className="truncate text-lg font-bold text-cyan-ink">{t.name}</h2>
          <p className="text-sm">
            <span>{info?.label ?? t.event}</span>
            {filter && <span className="ml-2 text-xs text-muted-foreground">{filter}</span>}
          </p>
          <p className="flex flex-wrap gap-x-3 text-xs text-muted-foreground">
            {t.owner && <span>Runs as {t.owner.name}</span>}
            <span>Agent: {t.agent?.name ?? "any free agent"}</span>
            {t.paused && <span>Paused</span>}
          </p>
          {t.broken && <p className="text-xs text-pink">Broken: {BROKEN_TEXT[t.broken]}</p>}
        </div>
        {canManage && (
          <span className="flex flex-wrap gap-2">
            {t.try_subject && info?.canTry && (
              <Button variant="ghost" onClick={() => void post("try")}>Try it on {t.try_subject}</Button>
            )}
            <Button variant="ghost" onClick={() => setEditing(true)}>Edit</Button>
            {t.paused ? (
              <Button variant="ghost" onClick={() => void post("resume")}>Resume</Button>
            ) : (
              <Button variant="ghost" onClick={() => void post("pause")}>Pause</Button>
            )}
            <Button variant="danger" onClick={remove}>Delete</Button>
          </span>
        )}
      </header>
      <pre className="rounded border border-line bg-surface-2 p-3 text-sm break-words whitespace-pre-wrap">{t.prompt}</pre>
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      <FiringList projectKey={key} triggerId={t.id} />
      {editing && <TriggerEditor projectKey={key} trigger={t} onClose={() => setEditing(false)} />}
      {dialog}
    </div>
  );
}
