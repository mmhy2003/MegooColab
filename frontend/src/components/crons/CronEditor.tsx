"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ScheduleField } from "@/components/crons/ScheduleField";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { useProjectAgents } from "@/lib/agents";
import { api } from "@/lib/api";
import { browserZone, cronKeys, cronsPath, type Cron, type CronMode, type CronRun } from "@/lib/crons";
import { errorMessage } from "@/lib/errors";

const MODES: { id: CronMode; title: string; text: string }[] = [
  { id: "report", title: "Report only", text: "Each run's report is kept here and you're told. Nothing else changes." },
  { id: "tasks", title: "Report, and open tasks for real problems",
    text: "It may create up to 5 tasks per run, labelled \"from cron\", checking first that one isn't already open." },
  { id: "kb", title: "Report, and keep one Knowledge Base document", text: "Each run rewrites this document." },
];

function zones(): string[] {
  const sv = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf;
  return sv ? sv("timeZone") : [browserZone()];
}

/** A cron, new or edited: its name, job, schedule (checked as typed), agent, what it may do and whom it tells. */
export function CronEditor({ projectKey, cron, onClose }: { projectKey: string; cron?: Cron; onClose: () => void }) {
  const client = useQueryClient();
  const agents = useProjectAgents(projectKey);
  const [name, setName] = useState(cron?.name ?? "");
  const [prompt, setPrompt] = useState(cron?.prompt ?? "");
  const [schedule, setSchedule] = useState(cron?.schedule ?? "0 9 * * 1-5");
  const [timezone, setTimezone] = useState(cron?.timezone ?? browserZone());
  const [agentId, setAgentId] = useState(cron?.agent?.id ?? "");
  const [mode, setMode] = useState<CronMode>(cron?.mode ?? "report");
  const [kbTitle, setKbTitle] = useState(cron?.kb_title ?? "");
  const [notify, setNotify] = useState({
    notify_findings: cron?.notify_findings ?? true,
    notify_every: cron?.notify_every ?? false,
    notify_failures: cron?.notify_failures ?? true,
  });
  const [valid, setValid] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tried, setTried] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = { name: name.trim(), prompt: prompt.trim(), schedule: schedule.trim(), timezone,
        agent_id: agentId || null, mode, kb_title: mode === "kb" ? kbTitle.trim() || null : null, ...notify };
      await api<Cron>(cron ? `${cronsPath(projectKey)}/${cron.id}` : cronsPath(projectKey),
        { method: cron ? "PATCH" : "POST", json: body });
      await client.invalidateQueries({ queryKey: cronKeys.all });
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const tryNow = async () => {
    if (!cron) return;
    try {
      const run = await api<CronRun>(`${cronsPath(projectKey)}/${cron.id}/run-now`, { method: "POST" });
      setTried(run.status === "skipped" ? "The last run is still going." : "Started: its report shows in the history.");
      await client.invalidateQueries({ queryKey: cronKeys.all });
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <Dialog open onClose={onClose} title={cron ? `Edit ${cron.name}` : `New cron · ${projectKey}`} wide>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void save(); }}>
        <Input label="Name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
        <div className="flex flex-col gap-1">
          <label htmlFor="cron-prompt" className="text-xs tracking-wider text-muted-foreground uppercase">
            What the agent should do
          </label>
          <textarea id="cron-prompt" value={prompt} maxLength={20000} onChange={(e) => setPrompt(e.target.value)}
            placeholder="For example: check the npm and Python dependencies for outdated or vulnerable packages."
            className="block min-h-24 w-full rounded border border-line bg-surface-2 p-2 text-sm" />
        </div>
        <ScheduleField value={schedule} timezone={timezone} onChange={setSchedule} onValid={setValid} />
        <Select label="Time zone" value={timezone} onChange={(e) => setTimezone(e.target.value)}>
          {zones().map((z) => (
            <option key={z} value={z}>{z}</option>
          ))}
        </Select>
        <Select label="Agent" value={agentId} onChange={(e) => setAgentId(e.target.value)}>
          <option value="">Any free agent of {projectKey}</option>
          {(agents.data ?? []).filter((a) => a.can_use).map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </Select>
        <fieldset className="space-y-1">
          <legend className="text-xs tracking-wider text-muted-foreground uppercase">What it may do with what it finds</legend>
          {MODES.map((m) => (
            <label key={m.id} className={`block rounded border px-3 py-2 ${mode === m.id ? "border-cyan" : "border-line"}`}>
              <input type="radio" name="cron-mode" className="mr-2" checked={mode === m.id} onChange={() => setMode(m.id)} />
              <b className="text-sm">{m.title}</b>
              <span className="block text-xs text-muted-foreground">{m.text}</span>
            </label>
          ))}
          {mode === "kb" && (
            <Input label="Document title" value={kbTitle} maxLength={200} placeholder={name || "The cron's name"}
              onChange={(e) => setKbTitle(e.target.value)} />
          )}
        </fieldset>
        <fieldset className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          <legend className="text-xs tracking-wider text-muted-foreground uppercase">Tell me</legend>
          {([["notify_findings", "when it finds something"], ["notify_every", "after every run"],
            ["notify_failures", "when it fails"]] as const).map(([k, label]) => (
            <label key={k} className="flex items-center gap-1">
              <input type="checkbox" checked={notify[k]} onChange={(e) => setNotify({ ...notify, [k]: e.target.checked })} />
              {label}
            </label>
          ))}
        </fieldset>
        {error && <p role="alert" className="text-sm text-pink">{error}</p>}
        {tried && <p className="text-sm text-muted-foreground">{tried}</p>}
        <div className="flex flex-wrap justify-end gap-2">
          {cron && <Button variant="ghost" onClick={tryNow}>Run once now to try it</Button>}
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy || !valid || !name.trim() || !prompt.trim()}>Save cron</Button>
        </div>
      </form>
    </Dialog>
  );
}
