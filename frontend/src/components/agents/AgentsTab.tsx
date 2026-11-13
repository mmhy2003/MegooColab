"use client";

import Link from "next/link";
import { useState } from "react";

import { AgentMenu } from "@/components/agents/AgentMenu";
import { AgentStatusDot } from "@/components/agents/AgentStatusDot";
import { MachineField } from "@/components/agents/MachineField";
import { ModelField } from "@/components/agents/ModelField";
import { ProjectBindings } from "@/components/agents/ProjectBindings";
import { RunnerUpdateArrow } from "@/components/agents/RunnerUpdateArrow";
import { RunsField, runsLabel } from "@/components/agents/RunsField";
import { StageModelsField } from "@/components/agents/StageModelsField";
import { Badge } from "@/components/ui/Badge";
import { ListDetail, ListRow, pickChosen, useChosenParam } from "@/components/ui/ListDetail";
import { api } from "@/lib/api";
import {
  PROGRAM_LABEL,
  STAGE_ROWS,
  cleanStages,
  effortLevels,
  effortName,
  findModel,
  sameEffort,
  staleStageEfforts,
  type StageModels,
} from "@/lib/agents";
import { errorMessage } from "@/lib/errors";
import type { AccessToken, Agent, Project } from "@/lib/types";

const projectCount = (n: number) => `${n} ${n === 1 ? "project" : "projects"}`;

function AgentDetails({
  agent,
  projects,
  tokens,
  onChanged,
  onDeleted,
}: {
  agent: Agent;
  projects: Project[];
  tokens: AccessToken[];
  onChanged: () => Promise<unknown>;
  onDeleted: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [stageNote, setStageNote] = useState<string | null>(null);
  const stages = (agent.stage_models ?? {}) as StageModels;
  const runs = runsLabel(agent.running ?? 0, agent.max_concurrent_runs);
  const patch = async (json: Record<string, unknown>) => {
    setError(null);
    try {
      await api(`/api/agents/${agent.id}`, { method: "PATCH", json });
      await onChanged();
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  const headingId = `agent-${agent.id}`;
  return (
    <section aria-labelledby={headingId} className="card min-w-0 space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-2">
        {/* on a phone the name has the line to itself; the badge, status and menu go under it */}
        <h2 id={headingId} className="min-w-0 flex-1 text-sm font-bold wrap-anywhere max-md:basis-full md:truncate">{agent.name}</h2>
        <Badge>{PROGRAM_LABEL[agent.program]}</Badge>
        <AgentStatusDot status={agent.status} />
        {runs && <span className="text-xs text-muted-foreground">{runs}</span>}
        <RunnerUpdateArrow runner={agent.runner} ownerId={agent.owner.id} />
        <AgentMenu agent={agent} onChanged={() => void onChanged()} onDeleted={onDeleted} onError={setError} />
      </div>
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      <div className="space-y-2">
        <h3 className="text-xs tracking-wider text-muted-foreground uppercase">Settings</h3>
        <div className="grid gap-3 md:grid-cols-2">
          <MachineField
            machine={agent.machine ?? null}
            tokens={tokens}
            value={agent.machine?.token_id ?? null}
            onChange={(tokenId) => void patch({ runner_token_id: tokenId })}
          />
          <ModelField
            model={agent.model ?? null}
            effort={agent.effort ?? null}
            knownModels={agent.known_models}
            onSave={(choice) => {
              setStageNote(null);
              if (choice.model === undefined) return patch(choice);
              // a stage with only an effort runs on the agent's model: one the new model lacks goes back to As above
              const stale = staleStageEfforts(stages, agent.known_models, choice.model);
              if (stale.length === 0) return patch(choice);
              const name = findModel(agent.known_models, choice.model)?.name ?? choice.model ?? "The program's default model";
              setStageNote(
                stale
                  .map((key) => {
                    const effort = stages[key]!.effort!;
                    const level = effortLevels(agent.known_models, agent.model ?? null).find((l) => sameEffort(l, effort));
                    const stage = STAGE_ROWS.find((r) => r.key === key)!.label;
                    return `${name} has no ${level?.name ?? effortName(effort)} effort, so ${stage}'s effort went back to As above.`;
                  })
                  .join(" "),
              );
              const kept: StageModels = { ...stages };
              for (const key of stale) kept[key] = { ...kept[key], effort: null };
              return patch({ ...choice, stage_models: cleanStages(kept) });
            }}
          />
          <RunsField
            key={agent.max_concurrent_runs}
            max={agent.max_concurrent_runs}
            running={agent.running ?? 0}
            onSave={(n) => patch({ max_concurrent_runs: n })}
          />
        </div>
      </div>
      <StageModelsField
        agentModel={agent.model ?? null}
        agentEffort={agent.effort ?? null}
        knownModels={agent.known_models}
        value={stages}
        notice={stageNote}
        onSave={(rows) => {
          setStageNote(null);
          return patch({ stage_models: rows });
        }}
      />
      <ProjectBindings agent={agent} projects={projects} onSaved={onChanged} />
    </section>
  );
}

/** My agents' Agents tab: one row per agent, the chosen one's settings and projects beside it. */
export function AgentsTab({
  agents,
  projects,
  tokens,
  hasMachines,
  onChanged,
}: {
  agents: Agent[];
  projects: Project[];
  tokens: AccessToken[];
  hasMachines: boolean;
  onChanged: () => Promise<unknown>;
}) {
  const [id, choose] = useChosenParam("agent");
  const { shown, chosen } = pickChosen(agents, id, (a) => a.id);
  if (agents.length === 0) {
    return (
      <div className="card space-y-1 px-3 py-6 text-center text-sm text-muted-foreground">
        <p>No agents yet.</p>
        {hasMachines ? (
          <p>Add one with Add agent.</p>
        ) : (
          <p>
            Set up the runner on a machine first: see <Link href="/settings/agents?tab=runner">Runner</Link>.
          </p>
        )}
      </div>
    );
  }
  return (
    <ListDetail
      listLabel="Agents"
      backLabel="Agents"
      chosen={chosen}
      onBack={() => choose(null)}
      list={
        <ul className="space-y-2">
          {agents.map((a) => {
            const runs = runsLabel(a.running ?? 0, a.max_concurrent_runs);
            return (
              <ListRow
                key={a.id}
                selected={a.id === shown?.id}
                onClick={() => choose(a.id)}
                title={
                  <>
                    <span className="min-w-0 flex-1 truncate">{a.name}</span>
                    {runs && <span className="text-xs font-normal text-muted-foreground">{runs}</span>}
                    <AgentStatusDot status={a.status} />
                  </>
                }
                meta={`${a.machine?.name ?? "Not linked"} · ${projectCount(a.bindings.length)}`}
              />
            );
          })}
        </ul>
      }
      detail={
        shown && (
          <AgentDetails
            key={shown.id}
            agent={shown}
            projects={projects}
            tokens={tokens}
            onChanged={onChanged}
            onDeleted={() => {
              choose(null);
              void onChanged();
            }}
          />
        )
      }
    />
  );
}
