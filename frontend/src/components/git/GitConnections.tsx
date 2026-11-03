"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import {
  GIT_KINDS,
  type GitConnection,
  type GitConnectionTest,
  type GitKind,
  gitTestError,
  HOSTED,
  TOKEN_DOCS,
  TOKEN_HELP,
  useGitConnections,
} from "@/lib/git";

const KIND_LABEL = Object.fromEntries(GIT_KINDS.map((k) => [k.value, k.label])) as Record<GitKind, string>;
const SET = "••••";

type Form = { name: string; kind: GitKind; hosted: boolean; base_url: string; token: string };

/** A row of buttons, one pressed: a choice with few options, all in view. */
function Choice<T extends string>({ label, value, options, onChange }: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="space-y-1">
      <span className="text-xs tracking-wider text-muted-foreground uppercase">{label}</span>
      <div role="group" aria-label={label} className="flex overflow-hidden rounded border border-line">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            aria-pressed={o.value === value}
            onClick={() => onChange(o.value)}
            className={`min-h-9 flex-1 px-2 text-sm ${o.value === value ? "bg-surface-2 font-semibold text-cyan-ink" : "text-muted-foreground hover:text-fg"}`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Add or edit a connection: the kind, hosted or self-hosted (only then an address), a name and the token. The
 * token is write-only: empty keeps what is saved. Webhook secrets are each repository's own now. */
function ConnectionForm({ editing, onDone }: { editing: GitConnection | null; onDone: () => void }) {
  const client = useQueryClient();
  const [form, setForm] = useState<Form>({
    name: editing?.name ?? "",
    kind: editing?.kind ?? "github",
    hosted: editing ? editing.hosted : true,
    base_url: editing && !editing.hosted ? editing.base_url : "",
    token: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<Form>) => setForm({ ...form, ...patch });
  const hostedOption = HOSTED[form.kind];
  const hosted = Boolean(hostedOption) && form.hosted;

  return (
    <form
      className="card space-y-3 p-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        const base_url = hosted ? hostedOption!.url : form.base_url;
        try {
          if (editing) {
            const patch: Record<string, string> = { name: form.name, base_url };
            if (form.token) patch.token = form.token;
            await api(`/api/admin/git-connections/${editing.id}`, { method: "PATCH", json: patch });
          } else {
            // a hosted service sends no address: the server knows it
            const body = { name: form.name, kind: form.kind, token: form.token, ...(hosted ? {} : { base_url }) };
            await api("/api/admin/git-connections", { method: "POST", json: body });
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
      {!editing && <Choice label="Kind" value={form.kind} options={GIT_KINDS} onChange={(kind) => set({ kind })} />}
      {hostedOption && (
        <Choice
          label="Where"
          value={form.hosted ? "hosted" : "self"}
          options={[{ value: "hosted", label: hostedOption.label }, { value: "self", label: "Self-hosted" }]}
          onChange={(v) => set({ hosted: v === "hosted" })}
        />
      )}
      {!hosted && (
        <div className="space-y-1">
          <Input label="Server address" required placeholder="https://git.example.com" value={form.base_url} onChange={(e) => set({ base_url: e.target.value })} />
          <p className="text-xs text-muted-foreground">Only for a self-hosted server. GitHub.com and GitLab.com need no address.</p>
        </div>
      )}
      <Input label="Name" required maxLength={100} value={form.name} onChange={(e) => set({ name: e.target.value })} />
      <div className="space-y-1">
        <Input
          label="Access token"
          type="password"
          autoComplete="off"
          required={!editing}
          placeholder={editing?.token_set ? SET : undefined}
          value={form.token}
          onChange={(e) => set({ token: e.target.value })}
        />
        <p className="text-xs text-muted-foreground">
          {TOKEN_HELP[form.kind]}{" "}
          <a href={TOKEN_DOCS[form.kind]} target="_blank" rel="noopener noreferrer">How to make one</a>
        </p>
      </div>
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>Save</Button>
        <Button variant="ghost" onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

function ConnectionRow({ c, onEdit }: { c: GitConnection; onEdit: () => void }) {
  const { ask, dialog } = useConfirm();
  const client = useQueryClient();
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <>
      <li className="space-y-2 px-3 py-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold">{c.name}</span>
          <span className="text-xs text-muted-foreground">{KIND_LABEL[c.kind]} · {c.base_url}</span>
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
              if (!(await ask({ tone: "danger", title: `Delete the connection ${c.name}?`, text: "Repositories linked to it stop being tracked.", ok: "Delete" }))) return;
              await api(`/api/admin/git-connections/${c.id}`, { method: "DELETE" });
              await client.invalidateQueries({ queryKey: ["git"] });
            }}
          >
            Delete
          </Button>
        </div>
        {result && <p role="status" className={`text-xs ${result.ok ? "text-green-ink" : "text-pink"}`}>{result.text}</p>}
        {c.webhook_secret_set && (
          <div className="space-y-1 rounded border border-amber/50 bg-amber/5 p-2 text-xs">
            <p>
              This provider still has a shared webhook secret from before. Repositories now each have their own: set them
              up, then remove the shared one.
            </p>
            {c.waiting_repositories.length > 0 && (
              <>
                <p className="text-muted-foreground">Still relying on it:</p>
                <ul className="list-disc pl-5">
                  {c.waiting_repositories.map((r) => (
                    <li key={`${r.project_key}/${r.name}`}>{r.project_key} · {r.name}</li>
                  ))}
                </ul>
              </>
            )}
            <Button
              variant="ghost"
              onClick={async () => {
                const waiting = c.waiting_repositories.length;
                if (waiting > 0 && !(await ask({
                  tone: "warn",
                  title: "Remove the shared secret?",
                  text: `${waiting === 1 ? "This repository hasn't" : `These ${waiting} repositories haven't`} set up their own webhook yet and would stop getting updates.`,
                  ok: "Remove",
                }))) return;
                await api(`/api/admin/git-connections/${c.id}`, { method: "PATCH", json: { webhook_secret: "" } });
                await client.invalidateQueries({ queryKey: ["git"] });
              }}
            >
              Remove shared secret
            </Button>
          </div>
        )}
      </li>
      {dialog}
    </>
  );
}

/** Admin → Git: the read-only provider tokens that follow pull requests (ADM-1, GIT-1). */
export function GitConnections() {
  const connections = useGitConnections();
  const [editing, setEditing] = useState<GitConnection | "new" | null>(null);
  if (connections.error) return <p className="text-sm text-pink">{errorMessage(connections.error)}</p>;
  if (!connections.data) return <p className="text-sm text-muted-foreground">Loading…</p>;
  return (
    <div className="space-y-4">
      <ul className="card divide-y divide-line">
        {connections.data.map((c) => (
          <ConnectionRow key={c.id} c={c} onEdit={() => setEditing(c)} />
        ))}
        {connections.data.length === 0 && <li className="px-3 py-3 text-sm text-muted-foreground">No git connections yet.</li>}
      </ul>
      {editing ? (
        <ConnectionForm key={editing === "new" ? "new" : editing.id} editing={editing === "new" ? null : editing} onDone={() => setEditing(null)} />
      ) : (
        <Button onClick={() => setEditing("new")}>Add connection</Button>
      )}
    </div>
  );
}
