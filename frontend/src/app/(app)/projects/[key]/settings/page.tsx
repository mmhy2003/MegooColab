"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";

import { ColumnEditor } from "@/components/project/ColumnEditor";
import { LabelEditor } from "@/components/project/LabelEditor";
import { RepoEditor } from "@/components/project/RepoEditor";
import { StatusSection } from "@/components/project/StatusSection";
import { WorkflowSettings } from "@/components/project/WorkflowSettings";
import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Input";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { canManage, useMe } from "@/lib/me";
import { useColumns, useLabels, useProject, useRepos, useTeams } from "@/lib/project";
import { qk } from "@/lib/queries";
import type { Project } from "@/lib/types";

const TABS = ["General", "Columns", "Repositories", "Labels", "Workflow"] as const;

function General({ project }: { project: Project }) {
  const client = useQueryClient();
  const teams = useTeams();
  const [form, setForm] = useState({
    name: project.name,
    description: project.description,
    sprints_enabled: project.sprints_enabled,
    team_ids: project.team_ids,
  });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  return (
    <form
      className="card max-w-xl space-y-4 p-4"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await api(`/api/projects/${project.key}`, { method: "PATCH", json: form });
          await client.invalidateQueries({ queryKey: qk.project(project.key) });
          await client.invalidateQueries({ queryKey: qk.projects() });
          setMsg({ ok: true, text: "Saved." });
        } catch (err) {
          setMsg({ ok: false, text: errorMessage(err) });
        }
      }}
    >
      <Input label="Name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      <Textarea label="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={form.sprints_enabled} onChange={(e) => setForm({ ...form, sprints_enabled: e.target.checked })} />
        Use sprints (backlog, sprint board, burndown and velocity)
      </label>
      <fieldset>
        <legend className="mb-1 text-xs tracking-wider text-muted-foreground uppercase">Teams</legend>
        <div className="flex flex-wrap gap-3">
          {teams.data?.map((t) => (
            <label key={t.id} className="flex items-center gap-1.5 text-sm">
              <input
                type="checkbox"
                checked={form.team_ids.includes(t.id)}
                onChange={(e) =>
                  setForm({
                    ...form,
                    team_ids: e.target.checked ? [...form.team_ids, t.id] : form.team_ids.filter((x) => x !== t.id),
                  })
                }
              />
              {t.name}
            </label>
          ))}
        </div>
      </fieldset>
      {msg && <p role="status" className={`text-sm ${msg.ok ? "text-green-ink" : "text-pink"}`}>{msg.text}</p>}
      <Button type="submit">Save</Button>
    </form>
  );
}

export default function ProjectSettingsPage() {
  const { key } = useParams<{ key: string }>();
  const client = useQueryClient();
  const project = useProject(key);
  const { data: me } = useMe();
  const columns = useColumns(key);
  const repos = useRepos(key);
  const labels = useLabels(key);
  const [tab, setTab] = useState<(typeof TABS)[number]>("General");

  if (!project.data) return null;
  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Settings sections" className="flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            type="button"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={`rounded border px-3 py-1 text-xs uppercase ${tab === t ? "border-cyan text-cyan-ink" : "border-line text-muted-foreground"}`}
          >
            {t}
          </button>
        ))}
      </div>
      {tab === "General" && (
        <>
          <StatusSection project={project.data} canChange={canManage(me)} />
          <General key={project.data.id} project={project.data} />
        </>
      )}
      {tab === "Columns" && columns.data && (
        <ColumnEditor projectKey={key} columns={columns.data} onChanged={() => client.invalidateQueries({ queryKey: qk.columns(key) })} />
      )}
      {tab === "Repositories" && repos.data && (
        <RepoEditor projectKey={key} repos={repos.data} onChanged={() => client.invalidateQueries({ queryKey: qk.repositories(key) })} />
      )}
      {tab === "Labels" && labels.data && (
        <LabelEditor projectKey={key} labels={labels.data} onChanged={() => client.invalidateQueries({ queryKey: qk.labels(key) })} />
      )}
      {tab === "Workflow" && <WorkflowSettings key={project.data.id} project={project.data} canEdit={canManage(me)} />}
    </div>
  );
}
