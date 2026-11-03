"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import type { Project } from "@/lib/types";
import type { ProjectAgent } from "@/lib/types";
import {
  DOCS_HELP,
  FINISHING_HELP,
  FINISHING_LABEL,
  OWN_AGENT_REVIEWS,
  PR_REVIEW_FORCES_PR,
  PR_REVIEW_HELP,
  PR_REVIEW_LABEL,
  SEND_BACK_HELP,
  type PrReview,
} from "@/lib/workflow";

const FINISHING: Project["finishing_option"][] = ["pull_request", "merge_local", "keep_branch"];
const PR_REVIEWS: PrReview[] = ["none", "human", "agent"];
const DOCS_LABEL = "Also commit design and plan to the repo";
const SEND_BACK_LABEL = "Send the task back when changes are requested on its pull request";

const yesNo = (on: boolean) => (on ? "On" : "Off");

export function WorkflowSettings({ project, canEdit }: { project: Project; canEdit: boolean }) {
  const client = useQueryClient();
  const [form, setForm] = useState({
    finishing_option: project.finishing_option,
    pr_review: project.pr_review as PrReview,
    pr_reviewer_agent_id: project.pr_reviewer_agent_id ?? null,
    commit_docs_to_repo: project.commit_docs_to_repo,
    send_back_on_changes_requested: project.send_back_on_changes_requested,
  });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  // the agents that could review: only asked for once Agent is chosen
  const agents = useQuery({
    queryKey: qk.projectAgents(project.key),
    queryFn: () => api<ProjectAgent[]>(`/api/projects/${project.key}/agents`),
    enabled: canEdit && form.pr_review === "agent",
  });

  if (!canEdit) {
    return (
      <section aria-label="Workflow" className="card max-w-xl space-y-3 p-4 text-sm">
        <div>
          <div className="text-xs tracking-wider text-muted-foreground uppercase">Default finishing option</div>
          <div>{FINISHING_LABEL[project.finishing_option]}</div>
          <p className="text-xs text-muted-foreground">{FINISHING_HELP[project.finishing_option]}</p>
        </div>
        <div>
          <div className="text-xs tracking-wider text-muted-foreground uppercase">Pull request review</div>
          <div>{PR_REVIEW_LABEL[project.pr_review as PrReview]}</div>
          <p className="text-xs text-muted-foreground">{PR_REVIEW_HELP[project.pr_review as PrReview]}</p>
        </div>
        <div>
          <div className="text-xs tracking-wider text-muted-foreground uppercase">{SEND_BACK_LABEL}</div>
          <div>{yesNo(project.send_back_on_changes_requested)}</div>
          <p className="text-xs text-muted-foreground">{SEND_BACK_HELP}</p>
        </div>
        <div>
          <div className="text-xs tracking-wider text-muted-foreground uppercase">{DOCS_LABEL}</div>
          <div>{yesNo(project.commit_docs_to_repo)}</div>
          <p className="text-xs text-muted-foreground">{DOCS_HELP}</p>
        </div>
        <p className="text-xs text-muted-foreground">
          {project.status === "active" ? "Only managers can change these." : "Read-only while the project is closed."}
        </p>
      </section>
    );
  }
  return (
    <form
      aria-label="Workflow"
      className="card max-w-xl space-y-4 p-4"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await api(`/api/projects/${project.key}`, { method: "PATCH", json: form });
          await client.invalidateQueries({ queryKey: qk.project(project.key) });
          setMsg({ ok: true, text: "Saved." });
        } catch (err) {
          setMsg({ ok: false, text: errorMessage(err) });
        }
      }}
    >
      <Select
        label="Default finishing option"
        value={form.finishing_option}
        onChange={(e) => setForm({ ...form, finishing_option: e.target.value as Project["finishing_option"] })}
      >
        {FINISHING.map((f) => (
          <option key={f} value={f}>
            {FINISHING_LABEL[f]}
          </option>
        ))}
      </Select>
      {/* what the chosen option does: it follows the choice */}
      <p className="-mt-2 text-xs text-muted-foreground">{FINISHING_HELP[form.finishing_option]}</p>
      <div className="space-y-1">
        <Select
          label="Pull request review"
          value={form.pr_review}
          onChange={(e) => setForm({ ...form, pr_review: e.target.value as PrReview })}
        >
          {PR_REVIEWS.map((r) => (
            <option key={r} value={r}>
              {PR_REVIEW_LABEL[r]}
            </option>
          ))}
        </Select>
        <p className="text-xs text-muted-foreground">{PR_REVIEW_HELP[form.pr_review]}</p>
        {form.pr_review !== "none" && <p className="text-xs text-muted-foreground">{PR_REVIEW_FORCES_PR}</p>}
      </div>
      {form.pr_review === "agent" && (
        <Select
          label="Reviewer"
          value={form.pr_reviewer_agent_id ?? ""}
          onChange={(e) => setForm({ ...form, pr_reviewer_agent_id: e.target.value || null })}
        >
          <option value="">{OWN_AGENT_REVIEWS}</option>
          {(agents.data ?? []).map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </Select>
      )}
      <div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.send_back_on_changes_requested}
            onChange={(e) => setForm({ ...form, send_back_on_changes_requested: e.target.checked })}
          />
          {SEND_BACK_LABEL}
        </label>
        <p className="ml-6 text-xs text-muted-foreground">{SEND_BACK_HELP}</p>
      </div>
      <div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.commit_docs_to_repo}
            onChange={(e) => setForm({ ...form, commit_docs_to_repo: e.target.checked })}
          />
          {DOCS_LABEL}
        </label>
        <p className="ml-6 text-xs text-muted-foreground">{DOCS_HELP}</p>
      </div>
      {msg && (
        <p role="status" className={`text-sm ${msg.ok ? "text-green-ink" : "text-pink"}`}>
          {msg.text}
        </p>
      )}
      <Button type="submit">Save</Button>
    </form>
  );
}
