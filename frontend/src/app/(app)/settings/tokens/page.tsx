"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { McpSetup } from "@/components/agents/McpSetup";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { CopyField } from "@/components/ui/CopyField";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import type { AccessToken, CreatedToken, TokenScope } from "@/lib/types";

const SCOPE_LABEL: Record<TokenScope, string> = { mcp: "MCP", runner: "Runner" };
const EXPIRY = [
  { value: "", label: "Never" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "365", label: "365 days" },
];

const when = (iso: string | null, empty: string) => (iso ? new Date(iso).toLocaleDateString() : empty);

function CreateTokenDialog({ onClose }: { onClose: () => void }) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<TokenScope[]>(["mcp"]);
  const [expiry, setExpiry] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [secret, setSecret] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () =>
      api<CreatedToken>("/api/tokens", {
        method: "POST",
        json: { name: name.trim(), scopes, expires_in_days: expiry ? Number(expiry) : null },
      }),
    onSuccess: async (res) => {
      setSecret(res.secret);
      await client.invalidateQueries({ queryKey: qk.tokens() });
    },
    onError: (err) => setError(errorMessage(err)),
  });

  const toggle = (s: TokenScope) =>
    setScopes((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]));

  return (
    <Dialog open title={secret ? "Token created" : "New access token"} onClose={onClose}>
      {secret ? (
        <div className="space-y-3">
          <CopyField label="Your token" value={secret} />
          <p role="alert" className="text-sm text-pink">You won&apos;t see this token again.</p>
          <div className="flex justify-end">
            <Button onClick={onClose}>Done</Button>
          </div>
        </div>
      ) : (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            create.mutate();
          }}
        >
          <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Laptop runner" required maxLength={100} />
          <fieldset className="space-y-1">
            <legend className="text-xs tracking-wider text-muted uppercase">Scopes</legend>
            {(["mcp", "runner"] as const).map((s) => (
              <label key={s} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={scopes.includes(s)} onChange={() => toggle(s)} />
                {SCOPE_LABEL[s]}
              </label>
            ))}
          </fieldset>
          <Select label="Expires" value={expiry} onChange={(e) => setExpiry(e.target.value)}>
            {EXPIRY.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </Select>
          {error && <p role="alert" className="text-sm text-pink">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={create.isPending || !name.trim() || scopes.length === 0}>Create token</Button>
          </div>
        </form>
      )}
    </Dialog>
  );
}

export default function TokensPage() {
  const client = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tokens = useQuery({ queryKey: qk.tokens(), queryFn: () => api<AccessToken[]>("/api/tokens") });
  const active = tokens.data?.filter((t) => !t.revoked_at) ?? [];

  return (
    <div className="space-y-8">
      <div>
        <PageHeader
          title="Access tokens"
          subtitle="Tokens let your runner and coding tools act as you. Treat them like passwords."
          actions={<Button onClick={() => setCreating(true)}>New token</Button>}
        />
        {error && <p role="alert" className="mb-2 text-sm text-pink">{error}</p>}
        <div className="card overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs tracking-wider text-muted uppercase">
              <tr className="border-b border-line">
                <th className="px-3 py-2 font-normal">Name</th>
                <th className="px-3 py-2 font-normal">Token</th>
                <th className="px-3 py-2 font-normal">Scopes</th>
                <th className="px-3 py-2 font-normal">Last used</th>
                <th className="px-3 py-2 font-normal">Expires</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {active.map((t) => (
                <tr key={t.id} className="border-b border-line last:border-0">
                  <td className="px-3 py-2">{t.name}</td>
                  <td className="px-3 py-2 font-mono text-xs text-muted">{t.prefix}…</td>
                  <td className="px-3 py-2">
                    <span className="flex gap-1">
                      {t.scopes.map((s) => (
                        <Badge key={s}>{SCOPE_LABEL[s]}</Badge>
                      ))}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-muted">{when(t.last_used_at, "Never")}</td>
                  <td className="px-3 py-2 text-muted">{when(t.expires_at, "Never")}</td>
                  <td className="px-3 py-2 text-right">
                    <Button
                      variant="danger"
                      aria-label={`Revoke ${t.name}`}
                      onClick={async () => {
                        if (!confirm(`Revoke ${t.name}? Anything using it stops working.`)) return;
                        try {
                          await api(`/api/tokens/${t.id}`, { method: "DELETE" });
                          await client.invalidateQueries({ queryKey: qk.tokens() });
                        } catch (err) {
                          setError(errorMessage(err));
                        }
                      }}
                    >
                      Revoke
                    </Button>
                  </td>
                </tr>
              ))}
              {tokens.data && active.length === 0 && (
                <tr><td colSpan={6} className="px-3 py-6 text-center text-muted">No tokens yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      <section className="card space-y-3 p-4">
        <h2 className="text-sm font-bold text-cyan-ink">Connect a coding tool over MCP</h2>
        <McpSetup />
      </section>
      {creating && <CreateTokenDialog onClose={() => setCreating(false)} />}
    </div>
  );
}
