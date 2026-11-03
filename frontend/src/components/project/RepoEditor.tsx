"use client";

import { Trash2 } from "lucide-react";
import { useState } from "react";

import { RepoPicker, type PickedRepo } from "@/components/project/RepoPicker";
import { WebhookDialog, webhookStatusText } from "@/components/project/WebhookDialog";
import { Button } from "@/components/ui/Button";
import { Hint } from "@/components/ui/Hint";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useConnectionNames } from "@/lib/git";
import type { Repo } from "@/lib/types";

const PROVIDERS: Repo["provider"][] = ["github", "gitlab", "gitea", "plain"];
const FIELD = "rounded border border-line bg-surface-2 px-2 py-1.5 text-sm";
const PILL: Record<Repo["webhook_status"], string> = {
  not_set_up: "border-amber/50 bg-amber/10 text-amber",
  working: "border-green/50 bg-green/10 text-green-ink",
  failing: "border-pink/50 bg-pink/10 text-pink",
};

/** A project's repositories: each one's connection and webhook, and adding one, picked from a provider's list or
 * entered by hand (a plain git server, or one the token can't list). */
export function RepoEditor({
  projectKey,
  repos,
  canEdit,
  onChanged,
}: {
  projectKey: string;
  repos: Repo[];
  /** manages the project (read-only otherwise) */
  canEdit: boolean;
  onChanged: () => void;
}) {
  const base = `/api/projects/${projectKey}/repositories`;
  const [form, setForm] = useState({ name: "", url: "", provider: "github" as Repo["provider"], default_branch: "main", connection_id: "" });
  const [byHand, setByHand] = useState(false);
  const [picked, setPicked] = useState<PickedRepo | null>(null);
  const [branch, setBranch] = useState("main");
  const [webhookFor, setWebhookFor] = useState<Repo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const connections = useConnectionNames();

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      const out = await fn();
      // a change that left the old host's webhook behind says so (its error code)
      const warning = (out as { warning?: string | null } | undefined)?.warning;
      if (warning) setError(`The webhook on the old host couldn't be removed (${warning}). Remove it there by hand.`);
      onChanged();
      return true;
    } catch (err) {
      setError(errorMessage(err));
      return false;
    }
  }

  return (
    <div className="space-y-3">
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      <ul className="card divide-y divide-line">
        {repos.map((r) => (
          <li key={r.id} className="space-y-1 px-3 py-2 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{r.name}</span>
              <span className="min-w-0 flex-1 truncate text-muted-foreground">{r.url}</span>
              <span className="text-xs text-muted-foreground">{r.provider} · {r.default_branch}</span>
              {canEdit ? (
                <>
                  <select
                    aria-label={`Connection for ${r.name}`}
                    title="The git connection that follows this repository's pull requests"
                    className={FIELD}
                    value={r.connection?.id ?? ""}
                    onChange={(e) => run(() => api(`${base}/${r.id}`, { method: "PATCH", json: { connection_id: e.target.value || null } }))}
                  >
                    <option value="">Not tracked</option>
                    {(connections.data ?? []).map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                  <Hint label={`Remove ${r.name}`}>
                    <button type="button" className="icon-btn hover:text-pink" aria-label={`Remove ${r.name}`} onClick={() => run(() => api(`${base}/${r.id}`, { method: "DELETE" }))}>
                      <Trash2 size={14} aria-hidden />
                    </button>
                  </Hint>
                </>
              ) : (
                <span className="text-xs text-muted-foreground">{r.connection ? `Tracked by ${r.connection.name}` : "Not tracked"}</span>
              )}
            </div>
            {r.connection && (
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded-full border px-2 text-xs ${PILL[r.webhook_status]}`}>{webhookStatusText(r.webhook_status, r.webhook_last_at)}</span>
                {canEdit && (
                  <Button variant={r.webhook_status === "not_set_up" ? "primary" : "ghost"} onClick={() => setWebhookFor(r)}>
                    {r.webhook_status === "not_set_up" ? "Set up webhook" : "Webhook"}
                  </Button>
                )}
              </div>
            )}
          </li>
        ))}
        {repos.length === 0 && <li className="px-3 py-3 text-sm text-muted-foreground">No repositories linked yet.</li>}
      </ul>
      {canEdit && (
        <div className="card space-y-3 p-3">
          <h3 className="text-xs tracking-wider text-muted-foreground uppercase">Add a repository</h3>
          {!byHand && (
            <>
              <RepoPicker
                projectKey={projectKey}
                onPick={(r) => {
                  setPicked(r);
                  setBranch(r.defaultBranch ?? "main");
                }}
              />
              {picked && (
                <form
                  className="flex flex-wrap items-end gap-2"
                  onSubmit={async (e) => {
                    e.preventDefault();
                    const body = { name: picked.path, url: picked.url, provider: picked.kind, default_branch: branch, connection_id: picked.connectionId };
                    if (await run(() => api(base, { method: "POST", json: body }))) setPicked(null);
                  }}
                >
                  <span className="min-w-0 flex-1 truncate text-sm font-semibold">{picked.path}</span>
                  <input aria-label="Default branch" className={`${FIELD} w-32`} value={branch} onChange={(e) => setBranch(e.target.value)} />
                  <Button type="submit">Add</Button>
                </form>
              )}
            </>
          )}
          {byHand && (
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={async (e) => {
                e.preventDefault();
                const body = { ...form, connection_id: form.connection_id || null };
                if (await run(() => api(base, { method: "POST", json: body }))) setForm({ ...form, name: "", url: "" });
              }}
            >
              <input aria-label="Repository name" placeholder="Name" required className={FIELD} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              <input aria-label="Repository URL" placeholder="https://… or git@…" required className={`${FIELD} min-w-64 flex-1`} value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
              <select aria-label="Provider" className={FIELD} value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value as Repo["provider"] })}>
                {PROVIDERS.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
              <input aria-label="Default branch" className={`${FIELD} w-28`} value={form.default_branch} onChange={(e) => setForm({ ...form, default_branch: e.target.value })} />
              <select aria-label="Connection" className={FIELD} value={form.connection_id} onChange={(e) => setForm({ ...form, connection_id: e.target.value })}>
                <option value="">Not tracked</option>
                {(connections.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              <Button type="submit" variant="ghost">Add</Button>
            </form>
          )}
          <button type="button" className="text-xs text-cyan-ink underline" onClick={() => setByHand(!byHand)}>
            {byHand ? "Pick it from a provider instead" : "Enter it by hand"}
          </button>
        </div>
      )}
      {webhookFor && (
        <WebhookDialog
          projectKey={projectKey}
          repo={webhookFor}
          onClose={() => {
            setWebhookFor(null);
            onChanged();
          }}
        />
      )}
    </div>
  );
}
