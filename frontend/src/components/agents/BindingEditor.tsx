"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import { isAbsolutePath } from "@/lib/agents";
import { errorMessage } from "@/lib/errors";
import type { Agent, Project } from "@/lib/types";

type Row = { project_ref: string; local_path: string };

/** Edits which projects an agent works on and where each repository lives on the owner's computer. */
export function BindingEditor({
  agent,
  projects,
  onSaved,
}: {
  agent: Agent;
  projects: Project[];
  onSaved: () => void;
}) {
  const [rows, setRows] = useState<Row[]>(
    agent.bindings.map((b) => ({ project_ref: b.project_key, local_path: b.local_path ?? "" })),
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const update = (i: number, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const save = async () => {
    setError(null);
    const bad = rows.find((r) => !r.project_ref || !isAbsolutePath(r.local_path.trim()));
    if (bad) {
      setError(
        bad.project_ref
          ? "Enter the full path to the repository, such as C:\\code\\payments or /home/me/code/payments."
          : "Choose a project for every row.",
      );
      return;
    }
    setSaving(true);
    try {
      await api(`/api/agents/${agent.id}/bindings`, {
        method: "PUT",
        json: { bindings: rows.map((r) => ({ project_ref: r.project_ref, local_path: r.local_path.trim() })) },
      });
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      {rows.length === 0 && <p className="text-sm text-muted-foreground">Not working on any project yet.</p>}
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-[minmax(0,1fr)] gap-2 sm:grid-cols-[12rem_1fr_auto] sm:items-end">
          <Select label="Project" value={r.project_ref} onChange={(e) => update(i, { project_ref: e.target.value })}>
            <option value="">Choose a project</option>
            {projects.map((p) => (
              <option key={p.id} value={p.key}>
                {p.key} {p.name}
              </option>
            ))}
          </Select>
          <Input
            label="Local path"
            placeholder="C:\code\payments or /home/me/code/payments"
            value={r.local_path}
            onChange={(e) => update(i, { local_path: e.target.value })}
          />
          <Button variant="ghost" aria-label={`Remove row ${i + 1}`} onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>
            Remove
          </Button>
        </div>
      ))}
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      <div className="flex gap-2">
        <Button variant="ghost" onClick={() => setRows((rs) => [...rs, { project_ref: "", local_path: "" }])}>
          Add project
        </Button>
        <Button onClick={save} disabled={saving}>Save bindings</Button>
      </div>
    </div>
  );
}
