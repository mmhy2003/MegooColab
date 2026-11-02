"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { MachineTools } from "@/components/hub/MachineTools";
import { ListDetail, ListRow, pickChosen, useChosenParam } from "@/components/ui/ListDetail";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { hubKeys, machineState, OS_LABEL, useHubMachines, useHubPrefs } from "@/lib/hub";

function DefaultSetSwitch() {
  const client = useQueryClient();
  const prefs = useHubPrefs();
  const [error, setError] = useState<string | null>(null);
  if (!prefs.data) return null;
  return (
    <div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={prefs.data.auto_default}
          onChange={async (e) => {
            setError(null);
            try {
              await api("/api/hub/prefs", { method: "PUT", json: { auto_default: e.target.checked } });
              await client.invalidateQueries({ queryKey: hubKeys.prefs() });
            } catch (err) {
              setError(errorMessage(err));
            }
          }}
        />
        When I add an agent on a new machine, install my default set there
      </label>
      <p className="mt-1 text-xs text-muted-foreground">
        Pick the default set on each tool&apos;s page in the <Link href="/hub">Tool Hub</Link>.
      </p>
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
    </div>
  );
}

/** My agents' Tools tab: one row per machine, the chosen machine's Tool Hub tools beside it. */
export function ToolsTab() {
  const machines = useHubMachines();
  const [id, choose] = useChosenParam("machine");
  const list = machines.data ?? [];
  const { shown, chosen } = pickChosen(list, id, (m) => m.token_id);
  return (
    <div className="space-y-4">
      <DefaultSetSwitch />
      {machines.error && <p role="alert" className="text-sm text-pink">{errorMessage(machines.error)}</p>}
      {machines.data?.length === 0 && (
        <div className="card space-y-1 px-3 py-6 text-center text-sm text-muted-foreground">
          <p>No machines yet.</p>
          <p>
            Set up the runner on one first: see <Link href="/settings/agents?tab=runner">Runner</Link>.
          </p>
        </div>
      )}
      {list.length > 0 && (
        <ListDetail
          listLabel="Machines"
          backLabel="Tools"
          chosen={chosen}
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
                      {m.out_of_step && <span aria-label="out of step" className="size-2 shrink-0 rounded-full bg-amber" />}
                    </>
                  }
                  meta={[m.os && (OS_LABEL[m.os] ?? m.os), machineState(m)].filter(Boolean).join(" · ")}
                />
              ))}
            </ul>
          }
          detail={
            // keyed by what the server said, so the ticks reset after a push or a report
            shown && <MachineTools key={`${shown.token_id}:${JSON.stringify(shown.tools)}`} machine={shown} />
          }
        />
      )}
    </div>
  );
}
