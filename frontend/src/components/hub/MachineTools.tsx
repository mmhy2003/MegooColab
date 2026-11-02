"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ImportDialog } from "@/components/hub/ImportDialog";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { PROGRAM_LABEL } from "@/lib/agents";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { hubKeys, OS_LABEL, PUSH_STATES, stateText, type HubMachine, type HubMachineState, type HubMachineTool } from "@/lib/hub";
import type { AgentProgram } from "@/lib/types";


const TONE: Partial<Record<HubMachineState, "green" | "amber" | "pink" | "cyan">> = {
  installed: "green", update_ready: "cyan", will_install: "cyan", changed: "amber", conflict: "amber",
  key_missing: "amber", removed: "pink", failed: "pink",
};

const programLabel = (p: string) => PROGRAM_LABEL[p as AgentProgram] ?? p;

const states = (t: HubMachineTool) => t.programs.map((p) => p.state).filter((s): s is HubMachineState => !!s);

/** One machine's Tool Hub tools: tick what it should have, push, and see what its runner reported. */
export function MachineTools({ machine }: { machine: HubMachine }) {
  const client = useQueryClient();
  const { ask, dialog } = useConfirm();
  const [ticked, setTicked] = useState<Set<string>>(
    () => new Set(machine.tools.filter((t) => t.ticked && t.tool_id).map((t) => t.tool_id!)),
  );
  const [takeOver, setTakeOver] = useState<Set<string>>(new Set());
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const os = machine.os ? OS_LABEL[machine.os] ?? machine.os : null;
  const fixed = (t: HubMachineTool) => !t.tool_id || states(t).includes("removed");
  const sendable = machine.tools.filter((t) => t.tool_id && ticked.has(t.tool_id) && !fixed(t));
  const changes = machine.tools.filter(
    (t) =>
      (t.tool_id && !fixed(t) && ticked.has(t.tool_id) !== t.ticked) ||
      states(t).some((s) => PUSH_STATES.has(s)) ||
      (t.tool_id && takeOver.has(t.tool_id)),
  ).length;

  const push = async () => {
    setError(null);
    if (sendable.some((t) => states(t).includes("changed"))) {
      const ok = await ask({
        tone: "warn",
        title: "Put your version back?",
        text: "This puts your library's version back over the hand edits on this machine.",
        ok: "Push",
      });
      if (!ok) return;
    }
    setBusy(true);
    try {
      await api(`/api/hub/machines/${machine.token_id}/push`, {
        method: "POST",
        json: { tool_ids: sendable.map((t) => t.tool_id), take_over: [...takeOver].filter((id) => ticked.has(id)) },
      });
      setTakeOver(new Set());
      await client.invalidateQueries({ queryKey: hubKeys.all });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card space-y-3 p-4" aria-labelledby={`tools-${machine.token_id}`}>
      {dialog}
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 id={`tools-${machine.token_id}`} className="flex-1 text-sm font-bold">Tools on &quot;{machine.name}&quot;</h3>
        <span className="text-xs text-muted-foreground">
          {[os, machine.online ? "connected" : "not connected"].filter(Boolean).join(" · ")}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        {machine.agents.length
          ? `Agents here: ${machine.agents.map((a) => `${a.name} (${programLabel(a.program)})`).join(", ")}`
          : "No agents on this machine yet."}
      </p>
      {machine.online && !machine.supports_tools ? (
        <p className="text-sm text-amber">Update the runner to use the Tool Hub.</p>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">
            Installed for your user on this machine, so every agent on it gets them, and so does your own Claude Code, Codex or OMP there.
          </p>
          {machine.tools.length === 0 ? (
            <p className="text-sm text-muted-foreground">Your Tool Hub is empty. Add an MCP or a skill there first.</p>
          ) : (
            <ul className="space-y-2">
              {machine.tools.map((t) => (
                <li key={t.tool_id ?? `${t.kind}:${t.name}`} aria-label={t.name} className="flex flex-wrap items-center gap-2 rounded border border-line p-2">
                  <input
                    type="checkbox"
                    aria-label={t.name}
                    disabled={fixed(t)}
                    checked={!!t.tool_id && ticked.has(t.tool_id) && !states(t).includes("removed")}
                    onChange={(e) => {
                      const next = new Set(ticked);
                      if (e.target.checked) next.add(t.tool_id!);
                      else next.delete(t.tool_id!);
                      setTicked(next);
                    }}
                  />
                  <span className="text-sm font-bold">{t.name}</span>
                  {t.kind === "mcp" ? <Badge tone="cyan">MCP</Badge> : <Badge tone="pink">Skill</Badge>}
                  <span className="flex-1" />
                  {t.programs.map((p) =>
                    p.state ? (
                      <Badge key={p.program} tone={TONE[p.state] ?? "muted"} className="normal-case">
                        {`${programLabel(p.program)}: ${stateText(p.state, programLabel(p.program), machine.os, p.detail ?? "")}`}
                      </Badge>
                    ) : null,
                  )}
                  {states(t).includes("conflict") && t.tool_id && (
                    <Button
                      variant="ghost"
                      aria-label={`Take over ${t.name}`}
                      aria-pressed={takeOver.has(t.tool_id)}
                      onClick={() => {
                        const next = new Set(takeOver);
                        if (next.has(t.tool_id!)) next.delete(t.tool_id!);
                        else next.add(t.tool_id!);
                        setTakeOver(next);
                      }}
                    >
                      Take over
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {error && <p role="alert" className="text-sm text-pink">{error}</p>}
          {/* on a phone the Push button stays on the screen while the list scrolls */}
          <div className="flex flex-wrap items-center gap-2 max-md:sticky max-md:bottom-0 max-md:-mx-4 max-md:border-t max-md:border-line max-md:bg-card max-md:px-4 max-md:py-2">
            <span className="flex-1 text-xs text-muted-foreground">
              {machine.reported_at ? `Last report: ${new Date(machine.reported_at).toLocaleString()}` : "Nothing reported yet."}
            </span>
            <Button variant="ghost" onClick={() => setImporting(true)}>Import from this machine</Button>
            <Button disabled={busy || changes === 0} onClick={push}>
              {`Push ${changes} ${changes === 1 ? "change" : "changes"}`}
            </Button>
          </div>
        </>
      )}
      {importing && <ImportDialog tokenId={machine.token_id} onClose={() => setImporting(false)} />}
    </section>
  );
}
