"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import type { Project } from "@/lib/types";

const FINISHING: { value: Project["finishing_option"]; label: string }[] = [
  { value: "pull_request", label: "Push and open a PR/MR" },
  { value: "merge_local", label: "Merge locally" },
  { value: "keep_branch", label: "Keep the branch" },
];
const REVIEW_LABEL = "Require human code review before Done";
const REVIEW_HELP = "Agents open a PR/MR and wait for a person to approve it before Done.";
const DOCS_LABEL = "Also commit design and plan to the repo";
const DOCS_HELP = "Also commits the approved design and plan under docs/superpowers/ in the task branch.";

const yesNo = (on: boolean) => (on ? "On" : "Off");

export function WorkflowSettings({ project, canEdit }: { project: Project; canEdit: boolean }) {
  const client = useQueryClient();
  const [form, setForm] = useState({
    finishing_option: project.finishing_option,
    require_human_code_review: project.require_human_code_review,
    commit_docs_to_repo: project.commit_docs_to_repo,
  });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  if (!canEdit) {
    return (
      <section aria-label="Workflow" className="card max-w-xl space-y-3 p-4 text-sm">
        <div>
          <div className="text-xs tracking-wider text-muted-foreground uppercase">Default finishing option</div>
          <div>{FINISHING.find((f) => f.value === project.finishing_option)?.label}</div>
        </div>
        <div>
          <div className="text-xs tracking-wider text-muted-foreground uppercase">{REVIEW_LABEL}</div>
          <div>{yesNo(project.require_human_code_review)}</div>
          <p className="text-xs text-muted-foreground">{REVIEW_HELP}</p>
        </div>
        <div>
          <div className="text-xs tracking-wider text-muted-foreground uppercase">{DOCS_LABEL}</div>
          <div>{yesNo(project.commit_docs_to_repo)}</div>
          <p className="text-xs text-muted-foreground">{DOCS_HELP}</p>
        </div>
        <p className="text-xs text-muted-foreground">Only managers can change these.</p>
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
          <option key={f.value} value={f.value}>
            {f.label}
          </option>
        ))}
      </Select>
      <div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.require_human_code_review}
            onChange={(e) => setForm({ ...form, require_human_code_review: e.target.checked })}
          />
          {REVIEW_LABEL}
        </label>
        <p className="ml-6 text-xs text-muted-foreground">{REVIEW_HELP}</p>
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
