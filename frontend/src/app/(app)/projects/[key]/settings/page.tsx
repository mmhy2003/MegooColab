"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Suspense, useState } from "react";

import { ColumnEditor } from "@/components/project/ColumnEditor";
import { DeleteProjectSection } from "@/components/project/DeleteProjectSection";
import { LabelEditor } from "@/components/project/LabelEditor";
import { RepoEditor } from "@/components/project/RepoEditor";
import { StatusSection } from "@/components/project/StatusSection";
import { WorkflowSettings } from "@/components/project/WorkflowSettings";
import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Input";
import { TabPanel, Tabs, useTabParam } from "@/components/ui/Tabs";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useMe } from "@/lib/me";
import { projectRights, teamChoices } from "@/lib/rights";
import { useColumns, useLabels, useProject, useRepos, useTeams } from "@/lib/project";
import { qk } from "@/lib/queries";
import type { Project } from "@/lib/types";

const TABS = [
  { id: "general", label: "General" },
  { id: "columns", label: "Columns" },
  { id: "repositories", label: "Repositories" },
  { id: "labels", label: "Labels" },
  { id: "workflow", label: "Workflow" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function General({ project, canEdit }: { project: Project; canEdit: boolean }) {
  const teams = useTeams();
  if (!canEdit) {
    const names = new Map(teams.data?.map((t) => [t.id, t.name]));
    const teamLine = !teams.data
      ? "Loading…"
      : project.team_ids.length === 0
        ? "None"
        : project.team_ids.map((id) => names.get(id) ?? "A team you can't see").join(", ");
    return (
      <dl className="card max-w-xl space-y-3 p-4 text-sm">
        <div><dt className="text-xs tracking-wider text-muted-foreground uppercase">Name</dt><dd>{project.name}</dd></div>
        <div><dt className="text-xs tracking-wider text-muted-foreground uppercase">Description</dt><dd>{project.description || "—"}</dd></div>
        <div><dt className="text-xs tracking-wider text-muted-foreground uppercase">Sprints</dt><dd>{project.sprints_enabled ? "On" : "Off"}</dd></div>
        <div>
          <dt className="text-xs tracking-wider text-muted-foreground uppercase">Teams</dt>
          <dd>{teamLine}</dd>
        </div>
      </dl>
    );
  }
  return <GeneralForm project={project} />;
}

function GeneralForm({ project }: { project: Project }) {
  const client = useQueryClient();
  const teams = useTeams();
  const { data: me } = useMe();
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
          {teamChoices(teams.data ?? [], me, project.team_ids).map((t) => (
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
  return (
    <Suspense>
      <ProjectSettings />
    </Suspense>
  );
}

function ProjectSettings() {
  const { key } = useParams<{ key: string }>();
  const client = useQueryClient();
  const project = useProject(key);
  const { data: me } = useMe();
  const columns = useColumns(key);
  const repos = useRepos(key);
  const labels = useLabels(key);
  const [tab, setTab] = useTabParam<TabId>(TABS.map((t) => t.id));

  if (!project.data) return null;
  const rights = projectRights(me, project.data);
  return (
    <div className="space-y-4">
      <Tabs label="Settings sections" tabs={TABS} value={tab} onChange={setTab} />
      <TabPanel id="general" active={tab === "general"}>
        <div className="space-y-4">
          <StatusSection project={project.data} canChange={rights.canChangeStatus} />
          <General key={project.data.id} project={project.data} canEdit={rights.canManage} />
          {me && <DeleteProjectSection project={project.data} user={me} />}
        </div>
      </TabPanel>
      <TabPanel id="columns" active={tab === "columns"}>
        {columns.data && (
          <ColumnEditor projectKey={key} columns={columns.data} canEdit={rights.canManage} onChanged={() => client.invalidateQueries({ queryKey: qk.columns(key) })} />
        )}
      </TabPanel>
      <TabPanel id="repositories" active={tab === "repositories"}>
        {repos.data && (
          <RepoEditor projectKey={key} repos={repos.data} canEdit={rights.canManage} onChanged={() => client.invalidateQueries({ queryKey: qk.repositories(key) })} />
        )}
      </TabPanel>
      <TabPanel id="labels" active={tab === "labels"}>
        {labels.data && (
          <LabelEditor projectKey={key} labels={labels.data} canEdit={rights.canManage} onChanged={() => client.invalidateQueries({ queryKey: qk.labels(key) })} />
        )}
      </TabPanel>
      <TabPanel id="workflow" active={tab === "workflow"}>
        <WorkflowSettings key={project.data.id} project={project.data} canEdit={rights.canManage} />
      </TabPanel>
    </div>
  );
}
