"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { BLANKED_MIN, SECRET_NAME, secretKeys, useOutdatedAgents, useSecrets, type Secret } from "@/lib/secrets";

const DOTS = "••••••••";

/** A list of secrets (a person's own, or a project's) with adding, editing, replacing a value and deleting. A value is
 * never shown: after saving, it can only be replaced. */
export function SecretsPanel({ base, canEdit, project }: { base: string; canEdit: boolean; project?: string }) {
  const client = useQueryClient();
  const secrets = useSecrets(base);
  const outdated = useOutdatedAgents(project);
  const { ask, dialog } = useConfirm();
  const [editing, setEditing] = useState<Secret | "new" | null>(null);
  const [replacing, setReplacing] = useState<Secret | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = () => client.invalidateQueries({ queryKey: secretKeys.list(base) });

  const remove = async (s: Secret) => {
    const ok = await ask({
      tone: "danger",
      title: `Delete ${s.name}?`,
      text: "Agents stop getting it on their next run.",
      ok: "Delete secret",
    });
    if (!ok) return;
    try {
      await api(`${base}/${s.id}`, { method: "DELETE" });
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">
          {project
            ? "Every agent that works on this project gets these as environment variables on its machine, where its owner could read them."
            : "Your agents get these as environment variables on their machines. Agents see only the names and descriptions, never a value."}
        </p>
        {canEdit && <Button onClick={() => setEditing("new")}>Add secret</Button>}
      </div>
      {(outdated.data ?? []).length > 0 && (
        <p className="rounded border border-amber/60 px-3 py-2 text-sm text-amber">
          These agents&apos; runners are too old to get secrets: {outdated.data!.map((a) => a.name).join(", ")}. Update
          megoocolab-runner on their machines.
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-pink">
          {error}
        </p>
      )}
      {secrets.data?.length === 0 && <p className="text-sm text-muted-foreground">No secrets yet.</p>}
      <ul className="divide-y divide-line rounded border border-line">
        {(secrets.data ?? []).map((s) => (
          <li key={s.id} className="flex min-w-0 flex-wrap items-start gap-x-4 gap-y-2 p-3">
            <div className="min-w-0 flex-1 basis-60">
              <p className="font-mono text-sm break-all text-cyan-ink">{s.name}</p>
              <p className="text-sm break-words">{s.description}</p>
              <p className="text-xs text-muted-foreground">
                <span className="tracking-widest">{DOTS}</span> · Changed {new Date(s.updated_at).toLocaleString()}
                {s.updated_by ? ` by ${s.updated_by.name}` : ""}
              </p>
            </div>
            {canEdit && (
              <div className="flex flex-wrap gap-2">
                <Button variant="ghost" onClick={() => setReplacing(s)}>
                  Replace value
                </Button>
                <Button variant="ghost" onClick={() => setEditing(s)}>
                  Edit
                </Button>
                <Button variant="danger" onClick={() => void remove(s)}>
                  Delete
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {editing && (
        <SecretDialog base={base} secret={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={refresh} />
      )}
      {replacing && <ValueDialog base={base} secret={replacing} onClose={() => setReplacing(null)} onSaved={refresh} />}
      {dialog}
    </section>
  );
}

function ValueField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [shown, setShown] = useState(false);
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor="secret-value" className="text-xs tracking-wider text-muted-foreground uppercase">
        Value
      </label>
      <div className="flex min-w-0 gap-2">
        <input
          id="secret-value"
          type={shown ? "text" : "password"}
          autoComplete="off"
          value={value}
          maxLength={32768}
          onChange={(e) => onChange(e.target.value)}
          className="min-w-0 flex-1 rounded border border-line bg-surface-2 px-2 py-1 font-mono text-sm"
        />
        <Button variant="ghost" aria-label={shown ? "Hide the value" : "Show the value"} onClick={() => setShown(!shown)}>
          {shown ? <EyeOff size={14} aria-hidden /> : <Eye size={14} aria-hidden />}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Encrypted before it is stored. After saving, nobody can see it again — only replace it.
      </p>
      {value.length > 0 && value.length < BLANKED_MIN && (
        <p className="text-xs text-amber">Values shorter than 4 characters can&apos;t be blanked out of what agents send back.</p>
      )}
    </div>
  );
}

function SecretDialog({ base, secret, onClose, onSaved }: {
  base: string; secret: Secret | null; onClose: () => void; onSaved: () => Promise<unknown>;
}) {
  const [name, setName] = useState(secret?.name ?? "");
  const [description, setDescription] = useState(secret?.description ?? "");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nameOk = SECRET_NAME.test(name);
  const ready = nameOk && description.trim() && (secret || value);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api(secret ? `${base}/${secret.id}` : base, {
        method: secret ? "PATCH" : "POST",
        json: secret ? { name, description: description.trim() } : { name, description: description.trim(), value },
      });
      await onSaved();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} title={secret ? `Edit ${secret.name}` : "Add secret"}>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <Input label="Environment variable name" value={name} maxLength={100} className="font-mono"
          onChange={(e) => setName(e.target.value)} />
        {name && !nameOk ? (
          <p className="text-xs text-pink">Capital letters, digits and _, starting with a letter</p>
        ) : (
          <p className="text-xs text-muted-foreground">Agents use it as ${name || "NAME"}.</p>
        )}
        <div className="flex flex-col gap-1">
          <label htmlFor="secret-description" className="text-xs tracking-wider text-muted-foreground uppercase">
            What it is (the agent reads this)
          </label>
          <textarea
            id="secret-description"
            value={description}
            maxLength={1000}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="For example: password of the staging Postgres, user megoo. Never production."
            className="block min-h-20 w-full rounded border border-line bg-surface-2 p-2 text-sm"
          />
        </div>
        {!secret && <ValueField value={value} onChange={setValue} />}
        {error && (
          <p role="alert" className="text-sm text-pink">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy || !ready}>
            Save secret
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function ValueDialog({ base, secret, onClose, onSaved }: {
  base: string; secret: Secret; onClose: () => void; onSaved: () => Promise<unknown>;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Dialog open onClose={onClose} title={`Replace the value of ${secret.name}`}>
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await api(`${base}/${secret.id}/value`, { method: "PUT", json: { value } });
            await onSaved();
            onClose();
          } catch (err) {
            setError(errorMessage(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <ValueField value={value} onChange={setValue} />
        {error && (
          <p role="alert" className="text-sm text-pink">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy || !value}>
            Save value
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
