"use client";

import { Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Repo } from "@/lib/types";

const PROVIDERS: Repo["provider"][] = ["github", "gitlab", "gitea", "plain"];
const FIELD = "rounded border border-line bg-surface-2 px-2 py-1.5 text-sm";

export function RepoEditor({ projectKey, repos, onChanged }: { projectKey: string; repos: Repo[]; onChanged: () => void }) {
  const base = `/api/projects/${projectKey}/repositories`;
  const [form, setForm] = useState({ name: "", url: "", provider: "github" as Repo["provider"], default_branch: "main" });
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
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
          <li key={r.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
            <span className="font-semibold">{r.name}</span>
            <span className="min-w-0 flex-1 truncate text-muted">{r.url}</span>
            <span className="text-xs text-muted">{r.provider} · {r.default_branch}</span>
            <button type="button" className="icon-btn hover:text-pink" aria-label={`Remove ${r.name}`} onClick={() => run(() => api(`${base}/${r.id}`, { method: "DELETE" }))}>
              <Trash2 size={14} aria-hidden />
            </button>
          </li>
        ))}
        {repos.length === 0 && <li className="px-3 py-3 text-sm text-muted">No repositories linked yet.</li>}
      </ul>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await run(() => api(base, { method: "POST", json: form }))) setForm({ ...form, name: "", url: "" });
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
        <Button type="submit" variant="ghost">Add</Button>
      </form>
    </div>
  );
}
