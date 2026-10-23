"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { AgentStatusDot } from "@/components/agents/AgentStatusDot";
import { BindingEditor } from "@/components/agents/BindingEditor";
import { RunnerSetup } from "@/components/agents/RunnerSetup";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import { ANSWER_MODE_HELP, PROGRAM_LABEL } from "@/lib/agents";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import type { Agent, AgentProgram, AnswerMode, Project } from "@/lib/types";

function AddAgentDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [program, setProgram] = useState<AgentProgram>("claude_code");
  const [name, setName] = useState("");
  const [answerMode, setAnswerMode] = useState<AnswerMode>("manual");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <Dialog open title="Add agent" onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await api("/api/agents", {
              method: "POST",
              json: { program, name: name.trim() || null, answer_mode: answerMode },
            });
            onCreated();
          } catch (err) {
            setError(errorMessage(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <Select label="Program" value={program} onChange={(e) => setProgram(e.target.value as AgentProgram)}>
          <option value="claude_code">{PROGRAM_LABEL.claude_code}</option>
          <option value="codex">{PROGRAM_LABEL.codex}</option>
        </Select>
        <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Leave blank for a default name" maxLength={200} />
        <div>
          <Select label="Answer mode" value={answerMode} onChange={(e) => setAnswerMode(e.target.value as AnswerMode)}>
            <option value="manual">Manual</option>
            <option value="auto">Auto</option>
          </Select>
          <p className="mt-1 text-xs text-muted">{ANSWER_MODE_HELP[answerMode]}</p>
        </div>
        {error && <p role="alert" className="text-sm text-pink">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy}>Add agent</Button>
        </div>
      </form>
    </Dialog>
  );
}

function AgentCard({ agent, projects, onChanged }: { agent: Agent; projects: Project[]; onChanged: () => void }) {
  const [error, setError] = useState<string | null>(null);
  return (
    <li className="card space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="flex-1 text-sm font-bold">{agent.name}</h3>
        <Badge>{PROGRAM_LABEL[agent.program]}</Badge>
        <AgentStatusDot status={agent.status} />
        <Button
          variant="danger"
          aria-label={`Delete ${agent.name}`}
          onClick={async () => {
            if (!confirm(`Delete ${agent.name}?`)) return;
            try {
              await api(`/api/agents/${agent.id}`, { method: "DELETE" });
              onChanged();
            } catch (err) {
              setError(errorMessage(err));
            }
          }}
        >
          Delete
        </Button>
      </div>
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      <BindingEditor agent={agent} projects={projects} onSaved={onChanged} />
    </li>
  );
}

export default function AgentsPage() {
  const client = useQueryClient();
  const [adding, setAdding] = useState(false);
  const agents = useQuery({ queryKey: qk.agents(), queryFn: () => api<Agent[]>("/api/agents/mine") });
  const projects = useQuery({ queryKey: qk.projects(), queryFn: () => api<Project[]>("/api/projects") });
  const refresh = () => client.invalidateQueries({ queryKey: qk.agents() });

  return (
    <div className="space-y-8">
      <div>
        <PageHeader
          title="My agents"
          subtitle="Register the coding agents on your computer and tell each one where a project's repository lives."
          actions={<Button onClick={() => setAdding(true)}>Add agent</Button>}
        />
        {agents.error && <p role="alert" className="text-sm text-pink">{errorMessage(agents.error)}</p>}
        <ul className="space-y-3">
          {agents.data?.map((a) => (
            // keyed by bindings so the editor resets when the saved bindings change
            <AgentCard
              key={`${a.id}:${a.bindings.map((b) => `${b.project_id}=${b.local_path}`).join("|")}`}
              agent={a}
              projects={projects.data ?? []}
              onChanged={refresh}
            />
          ))}
          {agents.data?.length === 0 && <li className="card px-3 py-6 text-center text-sm text-muted">No agents yet.</li>}
        </ul>
      </div>
      <section className="card space-y-3 p-4">
        <h2 className="text-sm font-bold text-cyan-ink">Install the runner</h2>
        <RunnerSetup />
      </section>
      {adding && (
        <AddAgentDialog
          onClose={() => setAdding(false)}
          onCreated={async () => {
            setAdding(false);
            await refresh();
          }}
        />
      )}
    </div>
  );
}
