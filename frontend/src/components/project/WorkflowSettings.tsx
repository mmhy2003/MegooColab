"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import type { Project } from "@/lib/types";
import { DOCS_HELP, FINISHING_HELP, FINISHING_LABEL, REVIEW_HELP } from "@/lib/workflow";

const FINISHING: Project["finishing_option"][] = ["pull_request", "merge_local", "keep_branch"];
const REVIEW_LABEL = "Require human code review before Done";
const DOCS_LABEL = "Also commit design and plan to the repo";

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
          <div>{FINISHING_LABEL[project.finishing_option]}</div>
          <p className="text-xs text-muted-foreground">{FINISHING_HELP[project.finishing_option]}</p>
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
