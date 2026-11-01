"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { PROGRAM_LABEL } from "@/lib/agents";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { hubKeys, type HubImportItem, type HubScan } from "@/lib/hub";
import type { AgentProgram } from "@/lib/types";

type Pick = { on: boolean; name: string; secret: Set<string> };

function initialPicks(items: HubImportItem[]): Record<number, Pick> {
  return Object.fromEntries(
    items.map((i) => [
      i.index,
      {
        on: !i.problem && !i.exists_in_library,
        name: i.name,
        secret: new Set([...(i.mcp?.headers ?? []), ...(i.mcp?.env ?? [])].filter((e) => e.suggested_secret).map((e) => e.name)),
      },
    ]),
  );
}

/** Brings what a machine already has set up by hand into the library. The machine itself is not changed. */
export function ImportDialog({
  tokenId,
  onClose,
  pollMs = 1500,
  timeoutMs = 60_000,
}: {
  tokenId: string;
  onClose: () => void;
  pollMs?: number;
  timeoutMs?: number;
}) {
  const client = useQueryClient();
  const [scanId, setScanId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);
  const [edits, setEdits] = useState<Record<number, Partial<Pick>>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api<{ scan_id: string }>(`/api/hub/machines/${tokenId}/scan`, { method: "POST" })
      .then((r) => live && setScanId(r.scan_id))
      .catch((err) => live && setError(errorMessage(err)));
    const timer = setTimeout(() => live && setTimedOut(true), timeoutMs);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [tokenId, timeoutMs]);

  const scan = useQuery({
    queryKey: hubKeys.scan(scanId ?? ""),
    queryFn: () => api<HubScan>(`/api/hub/scans/${scanId}`),
    enabled: scanId !== null,
    refetchInterval: (q) => (q.state.data?.status === "done" || timedOut ? false : pollMs),
  });
  const done = scan.data?.status === "done" ? scan.data.items : null;
  // what was found, as first suggested, with the person's changes on top
  const picks = useMemo(() => {
    if (!done) return null;
    const base = initialPicks(done);
    return Object.fromEntries(Object.entries(base).map(([k, v]) => [k, { ...v, ...edits[Number(k)] }])) as Record<number, Pick>;
  }, [done, edits]);

  const set = (index: number, patch: Partial<Pick>) => setEdits((e) => ({ ...e, [index]: { ...e[index], ...patch } }));
  const chosen = done && picks ? done.filter((i) => !i.problem && picks[i.index]?.on) : [];

  return (
    <Dialog open wide title="Import from this machine" onClose={onClose}>
      <div className="space-y-3">
        {error && <p role="alert" className="text-sm text-pink">{error}</p>}
        {scan.error && <p role="alert" className="text-sm text-pink">{errorMessage(scan.error)}</p>}
        {!error && !done && !timedOut && <p className="text-sm text-muted-foreground">Asking the machine what it has…</p>}
        {!done && timedOut && <p role="alert" className="text-sm text-pink">The machine didn&apos;t answer. Try again.</p>}
        {done && done.length === 0 && <p className="text-sm text-muted-foreground">Nothing set up by hand was found.</p>}
        {done && picks && (
          <ul className="max-h-[60vh] space-y-2 overflow-y-auto">
            {done.map((i) => {
              const pick = picks[i.index];
              return (
                <li key={i.index} className="space-y-2 rounded border border-line p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    {!i.problem && (
                      <input type="checkbox" aria-label={`Bring in ${i.name}`} checked={pick.on} onChange={(e) => set(i.index, { on: e.target.checked })} />
                    )}
                    <span className="font-bold">{i.name}</span>
                    {i.kind === "mcp" ? <Badge tone="cyan">MCP</Badge> : <Badge tone="pink">Skill</Badge>}
                    <span className="text-xs text-muted-foreground">{i.programs.map((p) => PROGRAM_LABEL[p as AgentProgram] ?? p).join(", ")}</span>
                    {i.exists_in_library && <span className="text-xs text-amber">Already in your library</span>}
                    {i.problem && <span className="text-xs text-pink">{i.problem}</span>}
                  </div>
                  {!i.problem && pick.on && (
                    <input
                      aria-label={`Name for ${i.name}`}
                      value={pick.name}
                      maxLength={64}
                      onChange={(e) => set(i.index, { name: e.target.value })}
                      className="w-full rounded border border-line bg-surface-2 px-2 py-1 font-mono text-sm"
                    />
                  )}
                  {i.mcp && (
                    <div className="space-y-1 text-xs">
                      <p className="font-mono">{i.mcp.transport === "http" ? i.mcp.url : [i.mcp.command, ...(i.mcp.args ?? [])].join(" ")}</p>
                      {[...(i.mcp.headers ?? []), ...(i.mcp.env ?? [])].map((e) => (
                        <label key={e.name} className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            aria-label={`${e.name} is secret`}
                            checked={pick.secret.has(e.name)}
                            onChange={(ev) => {
                              const next = new Set(pick.secret);
                              if (ev.target.checked) next.add(e.name);
                              else next.delete(e.name);
                              set(i.index, { secret: next });
                            }}
                          />
                          <span className="font-mono">{e.name}</span>
                          <span className="font-mono text-muted-foreground">{e.value_masked}</span>
                          <span className="text-muted-foreground">secret</span>
                        </label>
                      ))}
                    </div>
                  )}
                  {i.files && <p className="text-xs text-muted-foreground">{i.files.map((f) => f.path).join(", ")}</p>}
                </li>
              );
            })}
          </ul>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          {done && (
            <Button
              disabled={busy || chosen.length === 0}
              onClick={async () => {
                setError(null);
                setBusy(true);
                try {
                  await api(`/api/hub/scans/${scanId}/accept`, {
                    method: "POST",
                    json: {
                      items: chosen.map((i) => ({
                        index: i.index, name: picks![i.index].name.trim(), secret: [...picks![i.index].secret], description: "",
                      })),
                    },
                  });
                  await client.invalidateQueries({ queryKey: hubKeys.all });
                  onClose();
                } catch (err) {
                  setError(errorMessage(err));
                } finally {
                  setBusy(false);
                }
              }}
            >
              {`Add ${chosen.length} to my library`}
            </Button>
          )}
        </div>
      </div>
    </Dialog>
  );
}
