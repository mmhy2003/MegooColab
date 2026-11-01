"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { SkillFiles } from "@/components/hub/SkillFiles";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { hubKeys, type HubSpec, type HubTool } from "@/lib/hub";

const SYSTEM_LABEL: Record<string, string> = { windows: "Windows", linux: "Linux", macos: "macOS" };

/** An MCP's setup as text, with each secret shown as the slot the reader fills in themselves. */
export function SetupText({ spec }: { spec: HubSpec }) {
  const rows: string[] = [];
  if (spec.transport === "http") {
    rows.push(`web address  ${spec.url ?? ""}`);
    for (const h of spec.headers ?? []) rows.push(`header  ${h.name} = ${h.secret ? `‹your ${h.name}›` : h.value}`);
  } else {
    if (spec.command) rows.push(`command  ${[spec.command.command, ...(spec.command.args ?? [])].join(" ")}`);
    for (const [system, c] of Object.entries(spec.os_commands ?? {})) {
      rows.push(`${SYSTEM_LABEL[system] ?? system}  ${[c.command, ...(c.args ?? [])].join(" ")}`);
    }
    for (const e of spec.env ?? []) rows.push(`env  ${e.name} = ${e.secret ? `‹your ${e.name}›` : e.value}`);
  }
  return <pre className="overflow-x-auto rounded bg-surface-2 p-2 text-xs">{rows.join("\n")}</pre>;
}

/** What it runs on your machine, said before you take it. */
function RunsWarning({ tool }: { tool: HubTool }) {
  if (tool.kind === "skill") {
    const scripts = (tool.files ?? []).filter((f) => f.runs_on);
    if (scripts.length === 0) return null;
    return (
      <div role="note" className="rounded border border-amber p-3 text-sm">
        <p>This skill includes files your agents may run on your machine:</p>
        <ul className="mt-1 list-disc pl-5 font-mono text-xs">
          {scripts.map((f) => (
            <li key={f.path}>
              {f.path} ({(f.runs_on ?? []).map((s) => SYSTEM_LABEL[s] ?? s).join(", ")})
            </li>
          ))}
        </ul>
      </div>
    );
  }
  if (tool.spec?.transport !== "stdio") return null;
  const programs = [tool.spec.command?.command, ...Object.values(tool.spec.os_commands ?? {}).map((c) => c.command)].filter(Boolean);
  return (
    <div role="note" className="rounded border border-amber p-3 text-sm">
      This MCP runs a program on your machine: {[...new Set(programs)].join(", ")}
    </div>
  );
}

/** Someone else's tool: everything it holds, open to read, and a way to take a copy. Never their secrets. */
export function SharedToolView({ tool }: { tool: HubTool }) {
  const router = useRouter();
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">by {tool.owner.name}</p>
      <RunsWarning tool={tool} />
      {tool.spec && (
        <section className="card space-y-2 p-4">
          <h2 className="text-sm font-bold">Setup</h2>
          <SetupText spec={tool.spec} />
          {tool.secrets.length > 0 && (
            <ul className="flex flex-wrap gap-2">
              {tool.secrets.map((s) => (
                <li key={s.name} className="rounded border border-line px-2 py-0.5 text-xs">needs {s.name}</li>
              ))}
            </ul>
          )}
        </section>
      )}
      {tool.kind === "skill" && (
        <section className="card space-y-2 p-4">
          <h2 className="text-sm font-bold">Files</h2>
          <SkillFiles tool={tool} />
        </section>
      )}
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      <Button
        disabled={busy}
        onClick={async () => {
          setError(null);
          setBusy(true);
          try {
            const copy = await api<HubTool>(`/api/hub/tools/${tool.id}/copy`, { method: "POST" });
            await client.invalidateQueries({ queryKey: hubKeys.all });
            router.push(`/hub/${copy.id}`);
          } catch (err) {
            setError(errorMessage(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        Add to my library
      </Button>
    </div>
  );
}
