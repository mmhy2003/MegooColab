"use client";

import Link from "next/link";

import { Select } from "@/components/ui/Select";
import type { AccessToken, Machine } from "@/lib/types";

/** Runner tokens an agent can be linked to: the Runner scope, not revoked, not expired. */
export function usableRunnerTokens(tokens: AccessToken[], now = Date.now()): AccessToken[] {
  return tokens.filter(
    (t) => t.scopes.includes("runner") && !t.revoked_at && (!t.expires_at || new Date(t.expires_at).getTime() > now),
  );
}

/** The agent's machine: the runner token whose runner runs it. */
export function MachineField({
  machine,
  tokens,
  value,
  onChange,
}: {
  machine: Machine | null;
  tokens: AccessToken[];
  value: string | null;
  onChange: (tokenId: string | null) => void;
}) {
  const usable = usableRunnerTokens(tokens);
  return (
    <div className="space-y-1">
      <Select label="Machine" value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">Not linked</option>
        {/* the current link stays visible even once its token can no longer be picked */}
        {machine && !usable.some((t) => t.id === machine.token_id) && (
          <option value={machine.token_id} disabled>{machine.name}</option>
        )}
        {usable.map((t) => (
          <option key={t.id} value={t.id}>{t.name}</option>
        ))}
      </Select>
      {machine?.expired ? (
        <p className="text-xs text-pink">Machine token expired — pick another</p>
      ) : (
        value === null && (
          <p className="text-xs text-muted-foreground">
            Not linked to a machine — it stays offline until you pick its machine&apos;s token.
          </p>
        )
      )}
      {usable.length === 0 && (
        <p className="text-xs text-muted-foreground">
          Create a token with the Runner scope in <Link href="/settings/tokens">Access tokens</Link> first.
        </p>
      )}
    </div>
  );
}
