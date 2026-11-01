"use client";

import { useState } from "react";

import { EntriesEditor, type EntryRow } from "@/components/hub/EntriesEditor";
import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { errorMessage } from "@/lib/errors";
import type { HubSpec, HubTool } from "@/lib/hub";

export type McpBody = { name: string; description: string; read_only_safe: boolean; spec: HubSpec };

const SYSTEMS = [
  { id: "windows", label: "Windows" },
  { id: "linux", label: "Linux" },
  { id: "macos", label: "macOS" },
] as const;
type System = (typeof SYSTEMS)[number]["id"];

const PLACEHOLDER = /\$\{([A-Z0-9_]+)\}/g;

const lines = (text: string) => text.split("\n").map((l) => l.trim()).filter(Boolean);

function preview(spec: HubSpec): string {
  const shown = (rows: EntryRow[]) => rows.map((r) => `${r.name} = ${r.secret ? "‹their own›" : r.value}`);
  if (spec.transport === "http") return [`web address ${spec.url ?? ""}`, ...shown(spec.headers ?? []).map((l) => `header ${l}`)].join("\n");
  const cmd = spec.command ? [spec.command.command, ...(spec.command.args ?? [])].join(" ") : "(per system)";
  return [`command ${cmd}`, ...shown(spec.env ?? []).map((l) => `env ${l}`)].join("\n");
}

/** Adding or editing an MCP server: its setup, with secret values kept out (they are set separately). */
export function McpForm({
  initial,
  submitLabel,
  onSubmit,
  readOnly = false,
}: {
  initial?: HubTool;
  submitLabel: string;
  onSubmit: (body: McpBody) => Promise<void>;
  readOnly?: boolean;
}) {
  const s = initial?.spec;
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [transport, setTransport] = useState<"http" | "stdio">((s?.transport as "http" | "stdio") ?? "http");
  const [url, setUrl] = useState(s?.url ?? "");
  const [headers, setHeaders] = useState<EntryRow[]>((s?.headers ?? []) as EntryRow[]);
  const [command, setCommand] = useState(s?.command?.command ?? "");
  const [args, setArgs] = useState((s?.command?.args ?? []).join("\n"));
  const [osCommands, setOsCommands] = useState<Record<System, { command: string; args: string }>>(() => {
    const os = (s?.os_commands ?? {}) as Partial<Record<System, { command: string; args?: string[] }>>;
    return Object.fromEntries(
      SYSTEMS.map(({ id }) => [id, { command: os[id]?.command ?? "", args: (os[id]?.args ?? []).join("\n") }]),
    ) as Record<System, { command: string; args: string }>;
  });
  const [env, setEnv] = useState<EntryRow[]>((s?.env ?? []) as EntryRow[]);
  const [readOnlySafe, setReadOnlySafe] = useState(initial?.read_only_safe ?? false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const clean = (rows: EntryRow[]) =>
    rows.filter((r) => r.name.trim()).map((r) => ({ name: r.name.trim(), value: r.secret ? "" : r.value, secret: r.secret }));
  const spec: HubSpec = {
    transport,
    url: transport === "http" ? url.trim() : null,
    headers: transport === "http" ? clean(headers) : [],
    command: transport === "stdio" && command.trim() ? { command: command.trim(), args: lines(args) } : null,
    os_commands:
      transport === "stdio"
        ? Object.fromEntries(
            SYSTEMS.filter(({ id }) => osCommands[id].command.trim()).map(({ id }) => [
              id,
              { command: osCommands[id].command.trim(), args: lines(osCommands[id].args) },
            ]),
          )
        : {},
    env: transport === "stdio" ? clean(env) : [],
    acknowledged: s?.acknowledged ?? [],
  };

  const unknownPlaceholder = () => {
    const slots = new Set([...(spec.headers ?? []), ...(spec.env ?? [])].filter((e) => e.secret).map((e) => e.name));
    const texts = [spec.url ?? "", ...(spec.command?.args ?? []), ...Object.values(spec.os_commands ?? {}).flatMap((c) => c.args ?? [])];
    return texts.some((t) => [...t.matchAll(PLACEHOLDER)].some((m) => !slots.has(m[1])));
  };

  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        if (unknownPlaceholder()) {
          setError("A ${…} placeholder doesn't match any secret.");
          return;
        }
        setBusy(true);
        try {
          await onSubmit({ name: name.trim(), description: description.trim(), read_only_safe: readOnlySafe, spec });
        } catch (err) {
          setError(errorMessage(err));
        } finally {
          setBusy(false);
        }
      }}
    >
      <fieldset disabled={readOnly} className="space-y-3">
        <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="context7" maxLength={64} required />
        <Textarea label="Description" value={description} onChange={(e) => setDescription(e.target.value)} rows={2} maxLength={2000} />
        <Select label="Kind" value={transport} onChange={(e) => setTransport(e.target.value as "http" | "stdio")}>
          <option value="http">Web address</option>
          <option value="stdio">Command</option>
        </Select>
        {transport === "http" ? (
          <>
            <Input label="Address" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" maxLength={2000} required />
            <EntriesEditor label="Headers" noun="Header" rows={headers} onChange={setHeaders} />
          </>
        ) : (
          <>
            <Input label="Command" value={command} onChange={(e) => setCommand(e.target.value)} placeholder="npx" maxLength={500} />
            <Textarea label="Arguments" value={args} onChange={(e) => setArgs(e.target.value)} rows={3} placeholder="One per line" />
            <details className="rounded border border-line p-2">
              <summary className="cursor-pointer text-sm">Other systems</summary>
              <p className="mt-1 text-xs text-muted-foreground">Only when a system needs a different command. A system with none uses the one above.</p>
              {SYSTEMS.map(({ id, label }) => (
                <div key={id} className="mt-2 grid gap-2 sm:grid-cols-2">
                  <Input
                    label={`${label} command`}
                    value={osCommands[id].command}
                    onChange={(e) => setOsCommands({ ...osCommands, [id]: { ...osCommands[id], command: e.target.value } })}
                    maxLength={500}
                  />
                  <Textarea
                    label={`${label} arguments`}
                    value={osCommands[id].args}
                    onChange={(e) => setOsCommands({ ...osCommands, [id]: { ...osCommands[id], args: e.target.value } })}
                    rows={2}
                  />
                </div>
              ))}
            </details>
            <EntriesEditor label="Environment" noun="Variable" rows={env} onChange={setEnv} />
          </>
        )}
        <p className="text-xs text-muted-foreground">
          Put a secret inside the address or an argument as {"${NAME}"}, where NAME is one of the secret rows.
        </p>
      </fieldset>
      <div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={readOnlySafe} onChange={(e) => setReadOnlySafe(e.target.checked)} />
          Safe in read-only runs
        </label>
        <p className="mt-1 text-xs text-muted-foreground">Turn this on only for tools that read and never change anything outside.</p>
      </div>
      <div>
        <p className="text-xs tracking-wider text-muted-foreground uppercase">What others get</p>
        <pre className="mt-1 overflow-x-auto rounded bg-surface-2 p-2 text-xs">{preview(spec)}</pre>
      </div>
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      <div className="flex justify-end">
        <Button type="submit" disabled={busy}>{submitLabel}</Button>
      </div>
    </form>
  );
}
