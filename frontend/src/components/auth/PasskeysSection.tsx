"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { createPasskey, getPasskey, guessPasskeyName, isDismissed, passkeyProblem } from "@/lib/passkeys";
import { qk } from "@/lib/queries";
import type { Passkey } from "@/lib/types";

export function usePasskeys() {
  return useQuery({ queryKey: qk.passkeys(), queryFn: () => api<Passkey[]>("/api/auth/passkeys") });
}

const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

/** On while an authenticator app or any passkey is set up. */
export function TwoFactorStatus({ totpEnabled }: { totpEnabled: boolean }) {
  const passkeys = usePasskeys();
  if (!passkeys.data && !totpEnabled) return null;
  const on = totpEnabled || (passkeys.data?.length ?? 0) > 0;
  return (
    <p className={`text-sm ${on ? "text-green-ink" : "text-muted-foreground"}`}>
      {on ? "Two-factor sign-in is on." : "Two-factor sign-in is off."}{" "}
      <span className="text-muted-foreground">It is on while an authenticator app or a passkey is set up.</span>
    </p>
  );
}

/** Removing needs the password and a second factor: a passkey, or the app's code. */
function RemoveDialog({ passkey, totpEnabled, onClose, onRemoved }: { passkey: Passkey; totpEnabled: boolean; onClose: () => void; onRemoved: () => void }) {
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const remove = async (factor: Record<string, unknown>) => {
    await api(`/api/auth/passkeys/${passkey.id}`, { method: "DELETE", json: { password, ...factor } });
    onRemoved();
  };
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(isDismissed(err) ? "The passkey wasn't used. Try again." : errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open title={`Remove ${passkey.name}?`} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground">Confirm it&apos;s you: your password, then a passkey{totpEnabled ? " or your authenticator code" : ""}.</p>
        <Input label="Password" type="password" autoComplete="current-password" data-autofocus required value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p role="alert" className="text-sm text-pink">{error}</p>}
        <Button
          variant="danger"
          className="w-full"
          disabled={busy || !password}
          onClick={() =>
            run(async () => {
              const options = await api(`/api/auth/passkeys/${passkey.id}/remove-options`, { method: "POST" });
              await remove({ passkey: await getPasskey(options) });
            })
          }
        >
          Confirm with passkey
        </Button>
        {totpEnabled && (
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <Input label="Authenticator code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
            </div>
            <Button variant="ghost" disabled={busy || !password || !code} onClick={() => run(() => remove({ totp_code: code }))}>
              Remove with code
            </Button>
          </div>
        )}
      </div>
    </Dialog>
  );
}

/** Profile › Two-factor sign-in: the person's passkeys, adding and removing them. */
export function PasskeysSection({ totpEnabled }: { totpEnabled: boolean }) {
  const client = useQueryClient();
  const passkeys = usePasskeys();
  const [credential, setCredential] = useState<unknown | null>(null); // made by the browser, waiting for its name
  const [name, setName] = useState("");
  const [removing, setRemoving] = useState<Passkey | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const refresh = () => client.invalidateQueries({ queryKey: qk.passkeys() });

  const add = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const options = await api("/api/auth/passkeys/options", { method: "POST" });
      setCredential(await createPasskey(options));
      setName(guessPasskeyName(navigator.userAgent));
    } catch (err) {
      setMsg({ ok: false, text: isDismissed(err) ? "The passkey wasn't added." : (passkeyProblem(err) ?? errorMessage(err)) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-bold">Passkeys</h3>
      <p className="text-sm text-muted-foreground">Sign in with your fingerprint, face, device PIN or a security key instead of a code.</p>
      {passkeys.data && passkeys.data.length > 0 && (
        <ul className="divide-y divide-line">
          {passkeys.data.map((p) => (
            <li key={p.id} className="flex items-center gap-3 py-2">
              <KeyRound size={16} aria-hidden className="shrink-0 text-cyan-ink" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm">{p.name}</div>
                <div className="text-xs text-muted-foreground">
                  Added {day(p.created_at)} · last used {p.last_used_at ? day(p.last_used_at) : "never"}
                </div>
              </div>
              <Button variant="danger" aria-label={`Remove ${p.name}`} onClick={() => setRemoving(p)}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
      {credential ? (
        <form
          className="flex items-end gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              await api("/api/auth/passkeys", { method: "POST", json: { name: name.trim(), credential } });
              setCredential(null);
              setMsg({ ok: true, text: "Passkey added." });
              await refresh();
            } catch (err) {
              setCredential(null);
              setMsg({ ok: false, text: errorMessage(err) });
            } finally {
              setBusy(false);
            }
          }}
        >
          <div className="flex-1">
            <Input label="Passkey name" required maxLength={100} data-autofocus value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <Button type="submit" disabled={busy || !name.trim()} aria-label="Save passkey">
            Save
          </Button>
        </form>
      ) : (
        <Button disabled={busy} onClick={add}>
          Add a passkey
        </Button>
      )}
      {msg && <p className={`text-sm ${msg.ok ? "text-green-ink" : "text-pink"}`}>{msg.text}</p>}
      {removing && (
        <RemoveDialog
          passkey={removing}
          totpEnabled={totpEnabled}
          onClose={() => setRemoving(null)}
          onRemoved={() => {
            setRemoving(null);
            setMsg({ ok: true, text: "Passkey removed." });
            void refresh();
          }}
        />
      )}
    </div>
  );
}
