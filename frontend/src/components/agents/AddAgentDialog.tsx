"use client";

import { useState } from "react";

import { MachineField } from "@/components/agents/MachineField";
import { RUNS_HELP, RunsInput, parseRuns } from "@/components/agents/RunsField";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import { ANSWER_MODE_HELP, COMMON_EFFORTS, DEFAULT_MODEL, PROGRAM_LABEL } from "@/lib/agents";
import { errorMessage } from "@/lib/errors";
import type { AccessToken, Agent, AgentProgram, AnswerMode } from "@/lib/types";

/** Adding an agent: its program, name, machine, model and how it answers. Full screen on a phone. */
export function AddAgentDialog({
  tokens,
  initialMachine = null,
  onClose,
  onCreated,
}: {
  tokens: AccessToken[];
  initialMachine?: string | null;
  onClose: () => void;
  onCreated: (agent: Agent) => void;
}) {
  const [program, setProgram] = useState<AgentProgram>("claude_code");
  const [machine, setMachine] = useState<string | null>(initialMachine);
  const [name, setName] = useState("");
  const [answerMode, setAnswerMode] = useState<AnswerMode>("manual");
  const [model, setModel] = useState(DEFAULT_MODEL.claude_code);
  const [effort, setEffort] = useState("");
  const [runs, setRuns] = useState("1");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <Dialog open phoneFull title="Add agent" onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            const agent = await api<Agent>("/api/agents", {
              method: "POST",
              json: {
                program, name: name.trim() || null, answer_mode: answerMode, runner_token_id: machine,
                model: model.trim() || null, effort: effort || null, max_concurrent_runs: parseRuns(runs),
              },
            });
            onCreated(agent);
          } catch (err) {
            setError(errorMessage(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <Select
          label="Program"
          value={program}
          onChange={(e) => {
            const next = e.target.value as AgentProgram;
            setProgram(next);
            setModel(DEFAULT_MODEL[next]);
          }}
        >
          <option value="claude_code">{PROGRAM_LABEL.claude_code}</option>
          <option value="codex">{PROGRAM_LABEL.codex}</option>
          <option value="omp">{PROGRAM_LABEL.omp}</option>
        </Select>
        <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Leave blank for a default name" maxLength={200} />
        <MachineField machine={null} tokens={tokens} value={machine} onChange={setMachine} />
        <div>
          <Input label="Model" value={model} onChange={(e) => setModel(e.target.value)} placeholder="Program default" maxLength={100} />
          <p className="mt-1 text-xs text-muted-foreground">Leave it empty to use the program&apos;s own default. You can change it later.</p>
        </div>
        <div>
          <Select label="Effort" value={effort} onChange={(e) => setEffort(e.target.value)}>
            <option value="">Model default</option>
            {COMMON_EFFORTS.map((l) => (
              <option key={l.value} value={l.value}>{l.name}</option>
            ))}
          </Select>
          <p className="mt-1 text-xs text-muted-foreground">The levels each model supports are listed after the agent&apos;s first run.</p>
        </div>
        <div>
          <Select label="Answer mode" value={answerMode} onChange={(e) => setAnswerMode(e.target.value as AnswerMode)}>
            <option value="manual">Manual</option>
            <option value="auto">Auto</option>
          </Select>
          <p className="mt-1 text-xs text-muted-foreground">{ANSWER_MODE_HELP[answerMode]}</p>
        </div>
        <div>
          <RunsInput value={runs} onChange={setRuns} />
          <p className="mt-1 text-xs text-muted-foreground">{RUNS_HELP}</p>
        </div>
        {error && <p role="alert" className="text-sm text-pink">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy || parseRuns(runs) === null}>Add agent</Button>
        </div>
      </form>
    </Dialog>
  );
}
