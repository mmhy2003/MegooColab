"use client";

import Link from "next/link";

import { AddMachine } from "@/components/agents/AddMachine";
import { RunnerCommands } from "@/components/agents/RunnerCommands";
import { RunnerUpdateArrow } from "@/components/agents/RunnerUpdateArrow";
import { ListDetail, ListRow, pickChosen, useChosenParam } from "@/components/ui/ListDetail";
import { PROGRAM_LABEL } from "@/lib/agents";
import { errorMessage } from "@/lib/errors";
import { OS_LABEL, useHubMachines, type HubMachine } from "@/lib/hub";
import { useMe } from "@/lib/me";
import type { AgentProgram } from "@/lib/types";

const NEW = "new";
const osLabel = (os: string | null | undefined) => (os ? OS_LABEL[os] ?? os : null);
const agentCount = (n: number) => `${n} ${n === 1 ? "agent" : "agents"}`;

function MachineDetails({ machine }: { machine: HubMachine }) {
  const headingId = `runner-${machine.token_id}`;
  // the runner's hello records the machine's OS: none yet means it never connected
  const neverConnected = !machine.online && !machine.os;
  const facts = [
    machine.online ? "Connected" : "Not connected",
    osLabel(machine.os),
    machine.runner_version && `runner ${machine.runner_version}`,
  ].filter(Boolean);
  return (
    <section aria-labelledby={headingId} className="card min-w-0 space-y-4 p-4">
      <div className="space-y-1">
        <h2 id={headingId} className="truncate text-sm font-bold">{machine.name}</h2>
        <p className="text-xs text-muted-foreground">{facts.join(" · ")}</p>
        <p className="text-xs text-muted-foreground">
          {machine.agents.length
            ? `Agents on it: ${machine.agents.map((a) => `${a.name} (${PROGRAM_LABEL[a.program as AgentProgram] ?? a.program})`).join(", ")}`
            : "No agents on it yet."}
        </p>
      </div>
      {neverConnected ? (
        <p className="text-sm">
          This machine hasn&apos;t connected yet. Its token was shown once when you made it; if you no longer have it, set
          the machine up again with Add a machine and revoke this one under <Link href="/settings/tokens">Access tokens</Link>.
        </p>
      ) : (
        <RunnerCommands os={machine.os ?? null} />
      )}
    </section>
  );
}

/** My agents' Runner tab: your machines with their runner, and setting the runner up on a new one. */
export function RunnerTab({ onAddAgent }: { onAddAgent: (machine: string) => void }) {
  const machines = useHubMachines();
  const me = useMe().data?.id ?? "";
  const [id, choose] = useChosenParam("machine");
  const list = machines.data ?? [];
  const adding = id === NEW || (machines.data !== undefined && list.length === 0);
  const { shown, chosen } = pickChosen(adding ? [] : list, id, (m) => m.token_id);
  if (machines.error) return <p role="alert" className="text-sm text-pink">{errorMessage(machines.error)}</p>;
  if (!machines.data) return null;
  if (list.length === 0) return <AddMachine onAddAgent={onAddAgent} />;
  return (
    <ListDetail
      listLabel="Machines"
      backLabel="Runner"
      chosen={chosen || adding}
      onBack={() => choose(null)}
      list={
        <ul className="space-y-2">
          {list.map((m) => (
            <ListRow
              key={m.token_id}
              selected={m.token_id === shown?.token_id}
              onClick={() => choose(m.token_id)}
              title={
                <>
                  <span className="min-w-0 flex-1 truncate">{m.name}</span>
                  <span
                    aria-label={m.online ? "connected" : "not connected"}
                    className={`size-2 shrink-0 rounded-full ${m.online ? "bg-green" : "bg-muted-foreground"}`}
                  />
                </>
              }
              meta={[osLabel(m.os), m.runner_version && `runner ${m.runner_version}`, agentCount(m.agents.length)].filter(Boolean).join(" · ")}
              aside={m.runner_version && <RunnerUpdateArrow runner={{ version: m.runner_version, os: m.os ?? "" }} ownerId={me} />}
            />
          ))}
          <li>
            <button
              type="button"
              onClick={() => choose(NEW)}
              aria-current={adding ? "true" : undefined}
              className={`w-full rounded-lg border border-dashed px-3 py-2 text-sm font-bold ${adding ? "border-cyan bg-cyan/10" : "border-line hover:border-cyan/50"}`}
            >
              + Add a machine
            </button>
          </li>
        </ul>
      }
      detail={adding ? <AddMachine onAddAgent={onAddAgent} /> : shown && <MachineDetails key={shown.token_id} machine={shown} />}
    />
  );
}
