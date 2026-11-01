"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { MachineTools } from "@/components/hub/MachineTools";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { hubKeys, useHubMachines, useHubPrefs } from "@/lib/hub";

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

/** Tool Hub tools per machine, on My agents: a machine is where they are installed. */
export function HubMachines() {
  const machines = useHubMachines();
  return (
    <section aria-labelledby="hub-machines-heading" className="space-y-3">
      <h2 id="hub-machines-heading" className="text-sm font-bold text-cyan-ink">Tools on your machines</h2>
      <DefaultSetSwitch />
      {machines.error && <p role="alert" className="text-sm text-pink">{errorMessage(machines.error)}</p>}
      {machines.data?.length === 0 && (
        <p className="text-sm text-muted-foreground">No machines yet. Set up the runner below, then push your tools to it.</p>
      )}
      {machines.data?.map((m) => (
        // keyed by what the server said, so the ticks reset after a push or a report
        <MachineTools key={`${m.token_id}:${JSON.stringify(m.tools)}`} machine={m} />
      ))}
    </section>
  );
}
