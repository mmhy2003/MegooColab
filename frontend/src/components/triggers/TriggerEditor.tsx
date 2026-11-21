"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { useProjectAgents } from "@/lib/agents";
import { api } from "@/lib/api";
import { useCrons } from "@/lib/crons";
import { errorMessage } from "@/lib/errors";
import { useColumns, useLabels, useProject, useRepos } from "@/lib/project";
import {
  EVENTS, eventInfo, triggerKeys, triggersPath, type EventInfo, type TaskTypeName, type Trigger, type TriggerConfig,
} from "@/lib/triggers";

const TYPES: { id: TaskTypeName; label: string }[] = [
  { id: "story", label: "Story" }, { id: "task", label: "Task" }, { id: "bug", label: "Bug" },
];
const GROUPS: EventInfo["group"][] = ["Task events", "Sprint events", "Chains and larger events"];

/** A trigger, new or edited: its name, the event and its filter, the prompt, the agent, what happens after the
 * reply and whom it tells. */
export function TriggerEditor({ projectKey, trigger, onClose }: { projectKey: string; trigger?: Trigger; onClose: () => void }) {
  const client = useQueryClient();
  const project = useProject(projectKey);
  const agents = useProjectAgents(projectKey);
  const columns = useColumns(projectKey);
  const labels = useLabels(projectKey);
  const crons = useCrons(projectKey);
  const repos = useRepos(projectKey);
  const config = (trigger?.config ?? {}) as TriggerConfig;
  const [name, setName] = useState(trigger?.name ?? "");
  const [event, setEvent] = useState(trigger?.event ?? "task_finished");
  const [types, setTypes] = useState<TaskTypeName[]>(config.task_types ?? TYPES.map((t) => t.id));
  const [labelId, setLabelId] = useState(config.label_id ?? "");
  const [columnId, setColumnId] = useState(config.column_id ?? "");
  const [cronId, setCronId] = useState(config.cron_id ?? "");
  const [prompt, setPrompt] = useState(trigger?.prompt ?? "");
  const [agentId, setAgentId] = useState(trigger?.agent?.id ?? "");
  const [keepOpen, setKeepOpen] = useState(trigger?.keep_open ?? false);
  const [notify, setNotify] = useState({
    notify_reply: trigger?.notify_reply ?? true,
    notify_problems: trigger?.notify_problems ?? true,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const info = eventInfo(event);
  const fields = info?.fields ?? [];
  // the sprint events only where sprints are on; an edited trigger keeps showing its own event
  const events = EVENTS.filter((e) => !e.sprints || project.data?.sprints_enabled || e.id === trigger?.event);
  const webhookWorks = (repos.data ?? []).some((r) => r.webhook_status === "working");
  const incomplete = !name.trim() || !prompt.trim() || (fields.includes("types") && types.length === 0)
    || (fields.includes("column") && !columnId);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const sent: TriggerConfig = {};
      if (fields.includes("types")) {
        sent.task_types = TYPES.map((t) => t.id).filter((t) => types.includes(t));
        sent.label_id = labelId || null;
      }
      if (fields.includes("column")) sent.column_id = columnId;
      if (fields.includes("cron")) sent.cron_id = cronId || null;
      const body: Record<string, unknown> = { name: name.trim(), event, config: sent, prompt: prompt.trim(),
        keep_open: keepOpen, ...notify };
      // the agent is sent only when chosen here: another manager may edit a trigger whose agent they can't use
      if (!trigger || agentId !== (trigger.agent?.id ?? "")) body.agent_id = agentId || null;
      await api<Trigger>(trigger ? `${triggersPath(projectKey)}/${trigger.id}` : triggersPath(projectKey),
        { method: trigger ? "PATCH" : "POST", json: body });
      await client.invalidateQueries({ queryKey: triggerKeys.all });
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} title={trigger ? `Edit ${trigger.name}` : `New trigger · ${projectKey}`} wide>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void save(); }}>
        <Input label="Name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
        <Select label="When" value={event} onChange={(e) => setEvent(e.target.value)}>
          {GROUPS.map((g) => {
            const shown = events.filter((e) => e.group === g);
            return shown.length > 0 && (
              <optgroup key={g} label={g}>
                {shown.map((e) => (
                  <option key={e.id} value={e.id}>{e.label}</option>
                ))}
              </optgroup>
            );
          })}
        </Select>
        {fields.includes("column") && (
          <Select label="Column" value={columnId} onChange={(e) => setColumnId(e.target.value)}>
            <option value="">Choose a column</option>
            {(columns.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </Select>
        )}
        {fields.includes("types") && (
          <div className="flex flex-wrap items-end gap-4">
            <fieldset className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
              <legend className="text-xs tracking-wider text-muted-foreground uppercase">Only for</legend>
              {TYPES.map((t) => (
                <label key={t.id} className="flex items-center gap-1">
                  <input type="checkbox" checked={types.includes(t.id)}
                    onChange={(e) => setTypes(e.target.checked ? [...types, t.id] : types.filter((x) => x !== t.id))} />
                  {t.label}
                </label>
              ))}
            </fieldset>
            <Select label="Label" value={labelId} onChange={(e) => setLabelId(e.target.value)}>
              <option value="">Any label</option>
              {(labels.data ?? []).map((l) => (
                <option key={l.id} value={l.id}>{l.name}</option>
              ))}
            </Select>
          </div>
        )}
        {fields.includes("cron") && (
          <Select label="Cron" value={cronId} onChange={(e) => setCronId(e.target.value)}>
            <option value="">Any cron</option>
            {(crons.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </Select>
        )}
        {fields.includes("webhook") && (
          <p className="rounded border border-line px-3 py-2 text-sm text-muted-foreground">
            Needs the repository&apos;s own webhook.{" "}
            {webhookWorks ? "It is set up." : "It isn't set up yet: nothing fires until it is set up."}
          </p>
        )}
        <div className="flex flex-col gap-1">
          <label htmlFor="trigger-prompt" className="text-xs tracking-wider text-muted-foreground uppercase">Prompt</label>
          <textarea id="trigger-prompt" value={prompt} maxLength={8000} onChange={(e) => setPrompt(e.target.value)}
            placeholder="For example: write the release notes for this task and open a pull request with them."
            className="block min-h-24 w-full rounded border border-line bg-surface-2 p-2 text-sm" />
        </div>
        <div className="space-y-1">
          <p className="text-xs tracking-wider text-muted-foreground uppercase">What happened (added under your prompt)</p>
          <pre className="max-h-48 overflow-auto rounded border border-line bg-surface-2 p-2 text-xs whitespace-pre-wrap">
            {info?.example}
          </pre>
        </div>
        <Select label="Agent" value={agentId} onChange={(e) => setAgentId(e.target.value)}>
          <option value="">Any free agent of {projectKey}</option>
          {(agents.data ?? []).filter((a) => a.can_use).map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </Select>
        <fieldset className="space-y-1 text-sm">
          <legend className="text-xs tracking-wider text-muted-foreground uppercase">After the agent replies</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            <label className="flex items-center gap-1">
              <input type="radio" name="trigger-after" checked={!keepOpen} onChange={() => setKeepOpen(false)} />
              End the chat
            </label>
            <label className="flex items-center gap-1">
              <input type="radio" name="trigger-after" checked={keepOpen} onChange={() => setKeepOpen(true)} />
              Keep the chat open
            </label>
          </div>
          <p className="text-xs text-muted-foreground">A question or a failure keeps the chat open either way.</p>
        </fieldset>
        <fieldset className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          <legend className="text-xs tracking-wider text-muted-foreground uppercase">Tell me</legend>
          {([["notify_reply", "When the agent replies"], ["notify_problems", "When a firing is skipped or fails"]] as const)
            .map(([k, label]) => (
              <label key={k} className="flex items-center gap-1">
                <input type="checkbox" checked={notify[k]} onChange={(e) => setNotify({ ...notify, [k]: e.target.checked })} />
                {label}
              </label>
            ))}
        </fieldset>
        {trigger && <p className="text-sm text-muted-foreground">Saving makes you the person it runs as.</p>}
        {error && <p role="alert" className="text-sm text-pink">{error}</p>}
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy || incomplete}>Save trigger</Button>
        </div>
      </form>
    </Dialog>
  );
}
