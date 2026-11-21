"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";

import { TriggerEditor } from "@/components/triggers/TriggerEditor";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { useCrons } from "@/lib/crons";
import { errorMessage } from "@/lib/errors";
import { useColumns, useLabels } from "@/lib/project";
import {
  BROKEN_TEXT, RESULT_TEXT, SKIP_TEXT, eventInfo, filterText, triggerKeys, triggersPath, useTriggers,
  type Firing, type Trigger,
} from "@/lib/triggers";

/** "PAY-12 · Replied", or "PAY-14 · Skipped: No agent can take it". */
function firingText(f: Firing) {
  const result = RESULT_TEXT[f.result];
  const why = f.result === "skipped" && f.excerpt ? `: ${SKIP_TEXT[f.excerpt] ?? f.excerpt}` : "";
  return `${f.subject.label} · ${result}${why}`;
}

/** A project's triggers: what each sends, on which event, and how its last firing went. */
export function TriggerList({ projectKey, canManage }: { projectKey: string; canManage: boolean }) {
  const client = useQueryClient();
  const triggers = useTriggers(projectKey);
  const columns = useColumns(projectKey);
  const labels = useLabels(projectKey);
  const crons = useCrons(projectKey);
  const names = useMemo(() => ({
    columns: new Map((columns.data ?? []).map((c) => [c.id, c.name])),
    labels: new Map((labels.data ?? []).map((l) => [l.id, l.name])),
    crons: new Map((crons.data ?? []).map((c) => [c.id, c.name])),
  }), [columns.data, labels.data, crons.data]);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const act = async (trigger: Trigger, action: "pause" | "resume") => {
    setError(null);
    try {
      await api(`${triggersPath(projectKey)}/${trigger.id}/${action}`, { method: "POST" });
      await client.invalidateQueries({ queryKey: triggerKeys.all });
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">
          Prompts sent to one of the project&apos;s agents when something happens, each in a chat of its own.
        </p>
        {canManage && <Button onClick={() => setEditing(true)}>New trigger</Button>}
      </div>
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      {triggers.data?.length === 0 && <p className="text-sm text-muted-foreground">No triggers yet.</p>}
      <ul className="divide-y divide-line rounded border border-line">
        {(triggers.data ?? []).map((t) => {
          const filter = filterText(t, names);
          return (
            <li key={t.id} className="grid min-w-0 gap-x-4 gap-y-1 p-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1.4fr)_minmax(0,1.4fr)_auto]">
              <div className="min-w-0">
                <Link href={`/projects/${projectKey}/triggers/${t.id}`} className="font-semibold">{t.name}</Link>
                <p className="truncate text-xs text-muted-foreground">{t.prompt.split("\n")[0]}</p>
              </div>
              <div className="min-w-0 text-sm">
                <span>{eventInfo(t.event)?.label ?? t.event}</span>
                {filter && <span className="block text-xs text-muted-foreground">{filter}</span>}
                {t.broken && <span className="block text-xs text-pink">Broken: {BROKEN_TEXT[t.broken]}</span>}
              </div>
              <div className="min-w-0 text-sm">
                {t.paused && <span className="block text-xs text-muted-foreground">Paused</span>}
                <span className="block">{t.last_firing ? firingText(t.last_firing) : "Not fired yet"}</span>
              </div>
              {canManage && (
                <div className="flex flex-wrap items-start gap-2">
                  {t.paused ? (
                    <Button variant="ghost" onClick={() => void act(t, "resume")}>Resume</Button>
                  ) : (
                    <Button variant="ghost" onClick={() => void act(t, "pause")}>Pause</Button>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {editing && <TriggerEditor projectKey={projectKey} onClose={() => setEditing(false)} />}
    </section>
  );
}
