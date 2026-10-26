"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import type { AiProvider } from "@/lib/types";

type Draft = { name: string; kind: string; api_base: string; api_key: string; replaceKey: boolean };

const EMPTY: Draft = { name: "", kind: "openai", api_base: "", api_key: "", replaceKey: true };

/** AI providers (ADM-1). Keys are write-only: the server only says whether one is saved. */
export function ProviderList() {
  const client = useQueryClient();
  const providers = useQuery({ queryKey: qk.aiProviders(), queryFn: () => api<AiProvider[]>("/api/admin/ai/providers") });
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => client.invalidateQueries({ queryKey: ["ai"] });

  async function remove(p: AiProvider) {
    if (!confirm(`Delete provider ${p.name}?`)) return;
    setError(null);
    try {
      await api(`/api/admin/ai/providers/${p.id}`, { method: "DELETE" });
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <section className="card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-display text-sm font-semibold tracking-wider uppercase">Providers</h2>
        {editing === null && (
          <Button variant="ghost" onClick={() => setEditing("new")}>
            Add provider
          </Button>
        )}
      </div>
      {error && (
        <p role="alert" className="mb-2 text-sm text-pink">
          {error}
        </p>
      )}
      {editing === "new" && (
        <ProviderForm
          initial={EMPTY}
          onCancel={() => setEditing(null)}
          onSave={async (d) => {
            await api("/api/admin/ai/providers", {
              method: "POST",
              json: { name: d.name, kind: d.kind, api_base: d.api_base || null, api_key: d.api_key || null },
            });
            setEditing(null);
            await refresh();
          }}
        />
      )}
      <ul className="divide-y divide-line">
        {(providers.data ?? []).map((p) =>
          editing === p.id ? (
            <li key={p.id} className="py-3">
              <ProviderForm
                initial={{ name: p.name, kind: p.kind, api_base: p.api_base ?? "", api_key: "", replaceKey: !p.has_key }}
                hasKey={p.has_key}
                onCancel={() => setEditing(null)}
                onSave={async (d) => {
                  const body: Record<string, unknown> = { name: d.name, kind: d.kind, api_base: d.api_base || null };
                  if (d.replaceKey && d.api_key) body.api_key = d.api_key;
                  await api(`/api/admin/ai/providers/${p.id}`, { method: "PATCH", json: body });
                  setEditing(null);
                  await refresh();
                }}
              />
            </li>
          ) : (
            <li key={p.id} className="flex flex-wrap items-center gap-3 py-3 text-sm">
              <span className="font-semibold">{p.name}</span>
              <span className="font-mono text-xs text-muted">{p.kind}</span>
              {p.api_base && <span className="truncate font-mono text-xs text-muted">{p.api_base}</span>}
              {p.has_key ? (
                <span className="inline-flex items-center gap-1 text-xs text-green-ink">
                  <KeyRound size={12} aria-hidden /> Key saved
                </span>
              ) : (
                <span className="text-xs text-muted">No key</span>
              )}
              <span className="ml-auto flex gap-2">
                <Button variant="ghost" onClick={() => setEditing(p.id)}>
                  Edit
                </Button>
                <Button variant="danger" onClick={() => remove(p)}>
                  Delete
                </Button>
              </span>
            </li>
          ),
        )}
        {providers.data?.length === 0 && editing !== "new" && (
          <li className="py-3 text-sm text-muted">No providers yet. Semantic search stays off until one is set up.</li>
        )}
      </ul>
    </section>
  );
}

function ProviderForm({
  initial,
  hasKey = false,
  onSave,
  onCancel,
}: {
  initial: Draft;
  hasKey?: boolean;
  onSave: (d: Draft) => Promise<void>;
  onCancel: () => void;
}) {
  const [d, setD] = useState<Draft>(initial);
  const [error, setError] = useState<string | null>(null);
  const set = (patch: Partial<Draft>) => setD({ ...d, ...patch });
  return (
    <form
      className="mb-3 space-y-3 rounded border border-line p-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        try {
          await onSave(d);
        } catch (err) {
          setError(errorMessage(err));
        }
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Name" required maxLength={100} value={d.name} onChange={(e) => set({ name: e.target.value })} />
        <Input
          label="Kind"
          required
          maxLength={50}
          placeholder="openai, azure, ollama…"
          value={d.kind}
          onChange={(e) => set({ kind: e.target.value.trim().toLowerCase() })}
        />
      </div>
      <Input
        label="API base URL (optional)"
        maxLength={500}
        placeholder="https://…"
        value={d.api_base}
        onChange={(e) => set({ api_base: e.target.value })}
      />
      {d.replaceKey ? (
        <Input
          label="API key"
          type="password"
          autoComplete="new-password"
          value={d.api_key}
          onChange={(e) => set({ api_key: e.target.value })}
        />
      ) : (
        <p className="flex items-center gap-3 text-sm">
          <span className="text-green-ink">Key saved</span>
          <Button variant="ghost" onClick={() => set({ replaceKey: true })}>
            Replace key
          </Button>
        </p>
      )}
      {hasKey && d.replaceKey && <p className="text-xs text-muted">Leave empty to keep the saved key.</p>}
      {error && (
        <p role="alert" className="text-sm text-pink">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit">Save</Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
