"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { CopyField } from "@/components/ui/CopyField";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import {
  GIT_KINDS,
  type GitConnection,
  type GitConnectionTest,
  type GitKind,
  gitTestError,
  useGitConnections,
  webhookUrl,
} from "@/lib/git";

const KIND_LABEL = Object.fromEntries(GIT_KINDS.map((k) => [k.value, k.label])) as Record<GitKind, string>;
const SET = "••••";

type Form = { name: string; kind: GitKind; base_url: string; token: string; webhook_secret: string };

/** Add or edit a connection. The token and webhook secret are write-only: empty keeps what is saved. */
function ConnectionForm({ editing, onDone }: { editing: GitConnection | null; onDone: () => void }) {
  const client = useQueryClient();
  const [form, setForm] = useState<Form>({
    name: editing?.name ?? "",
    kind: editing?.kind ?? "github",
    base_url: editing?.base_url ?? "https://github.com",
    token: "",
    webhook_secret: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<Form>) => setForm({ ...form, ...patch });

  return (
    <form
      className="card space-y-3 p-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          if (editing) {
            const patch: Record<string, string> = { name: form.name, base_url: form.base_url };
            if (form.token) patch.token = form.token;
            if (form.webhook_secret) patch.webhook_secret = form.webhook_secret;
            await api(`/api/admin/git-connections/${editing.id}`, { method: "PATCH", json: patch });
          } else {
            await api("/api/admin/git-connections", { method: "POST", json: form });
          }
          await client.invalidateQueries({ queryKey: ["git"] });
          onDone();
        } catch (err) {
          setError(errorMessage(err));
        } finally {
          setBusy(false);
        }
      }}
    >
      <Input label="Name" required maxLength={100} value={form.name} onChange={(e) => set({ name: e.target.value })} />
      {!editing && (
        <Select label="Kind" value={form.kind} onChange={(e) => set({ kind: e.target.value as GitKind })}>
          {GIT_KINDS.map((k) => (
            <option key={k.value} value={k.value}>{k.label}</option>
          ))}
        </Select>
      )}
      <Input label="Base URL" required value={form.base_url} onChange={(e) => set({ base_url: e.target.value })} />
      <Input
        label="Token"
        type="password"
        autoComplete="off"
        required={!editing}
        placeholder={editing?.token_set ? SET : "A read-only token"}
        value={form.token}
        onChange={(e) => set({ token: e.target.value })}
      />
      <Input
        label="Webhook secret"
        type="password"
        autoComplete="off"
        placeholder={editing?.webhook_secret_set ? SET : "Optional: webhooks update pull requests at once"}
        value={form.webhook_secret}
        onChange={(e) => set({ webhook_secret: e.target.value })}
      />
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>Save</Button>
        <Button variant="ghost" onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

function ConnectionRow({ c, onEdit }: { c: GitConnection; onEdit: () => void }) {
  const client = useQueryClient();
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <li className="space-y-2 px-3 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{c.name}</span>
        <span className="text-xs text-muted">{KIND_LABEL[c.kind]} · {c.base_url}</span>
        <span className="flex-1" />
        <Button
          variant="ghost"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const r = await api<GitConnectionTest>(`/api/admin/git-connections/${c.id}/test`, { method: "POST" });
              setResult(r.ok ? { ok: true, text: `Connected as ${r.login}` } : { ok: false, text: gitTestError(r.error) });
            } catch (err) {
              setResult({ ok: false, text: errorMessage(err) });
            } finally {
              setBusy(false);
            }
          }}
        >
          Test
        </Button>
        <Button variant="ghost" onClick={onEdit}>Edit</Button>
        <Button
          variant="danger"
          onClick={async () => {
            if (!window.confirm(`Delete the connection ${c.name}? Repositories linked to it stop being tracked.`)) return;
            await api(`/api/admin/git-connections/${c.id}`, { method: "DELETE" });
            await client.invalidateQueries({ queryKey: ["git"] });
          }}
        >
          Delete
        </Button>
      </div>
      {result && <p role="status" className={`text-xs ${result.ok ? "text-green-ink" : "text-pink"}`}>{result.text}</p>}
      {c.webhook_secret_set ? (
        <CopyField label="Webhook URL" value={webhookUrl(c.id)} />
      ) : (
        <p className="text-xs text-muted">No webhook secret: pull requests are checked every 2 minutes.</p>
      )}
    </li>
  );
}

/** Admin → Git: the read-only provider tokens that follow pull requests (ADM-1, GIT-1). */
export function GitConnections() {
  const connections = useGitConnections();
  const [editing, setEditing] = useState<GitConnection | "new" | null>(null);
  if (connections.error) return <p className="text-sm text-pink">{errorMessage(connections.error)}</p>;
  if (!connections.data) return <p className="text-sm text-muted">Loading…</p>;
  return (
    <div className="space-y-4">
      <ul className="card divide-y divide-line">
        {connections.data.map((c) => (
          <ConnectionRow key={c.id} c={c} onEdit={() => setEditing(c)} />
        ))}
        {connections.data.length === 0 && <li className="px-3 py-3 text-sm text-muted">No git connections yet.</li>}
      </ul>
      {editing ? (
        <ConnectionForm key={editing === "new" ? "new" : editing.id} editing={editing === "new" ? null : editing} onDone={() => setEditing(null)} />
      ) : (
        <Button onClick={() => setEditing("new")}>Add connection</Button>
      )}
    </div>
  );
}
