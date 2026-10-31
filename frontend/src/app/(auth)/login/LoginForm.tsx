"use client";

import { X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { forgetAccount, rememberAccount, useRememberedAccounts, type RememberedAccount } from "@/lib/accounts";
import { ApiError, api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";

/** Only same-site paths are honoured, so a crafted link can't bounce users off-site. */
export function safeNext(next: string | null): string {
  // browsers treat "\" like "/", so "/\evil.com" would leave the site too
  return next && next.startsWith("/") && !next.startsWith("//") && !next.includes("\\") ? next : "/";
}

/** An account remembered on this browser: picking it asks for its password; × forgets it here. */
function AccountRow({ account, onPick }: { account: RememberedAccount; onPick: () => void }) {
  return (
    <li className="flex items-center gap-1 rounded border border-line bg-surface-2 hover:border-cyan">
      <button type="button" onClick={onPick} className="flex min-w-0 flex-1 items-center gap-3 px-3 py-2 text-left">
        <Avatar name={account.name} size={30} />
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-fg">{account.name}</span>
          <span className="block truncate text-xs text-muted-foreground">{account.email}</span>
        </span>
      </button>
      <button
        type="button"
        className="icon-btn mr-1 hover:text-pink"
        aria-label={`Forget ${account.email} on this browser`}
        title="Forget this account on this browser"
        onClick={() => forgetAccount(account.email)}
      >
        <X size={14} aria-hidden />
      </button>
    </li>
  );
}

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const accounts = useRememberedAccounts();
  const [picked, setPicked] = useState<RememberedAccount | null>(null);
  const [another, setAnother] = useState(false); // "Use another account": the form, with the list one click away
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needCode, setNeedCode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ needs_setup: boolean }>("/api/setup/status")
      .then((s) => s.needs_setup && router.replace("/setup"))
      .catch(() => undefined);
  }, [router]);

  const reset = () => {
    setPassword("");
    setCode("");
    setNeedCode(false);
    setError(null);
  };
  const pick = (account: RememberedAccount | null) => {
    reset();
    setPicked(account);
  };

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const signInAs = picked?.email ?? email;
    try {
      const { user } = await api<{ user: { email?: string; name?: string } }>("/api/auth/login", {
        method: "POST",
        json: { email: signInAs, password, totp_code: needCode ? code : undefined },
      });
      rememberAccount({ email: user.email ?? signInAs, name: user.name ?? signInAs });
      router.push(safeNext(params.get("next")));
    } catch (err) {
      if (err instanceof ApiError && err.detail === "totp_required") {
        setNeedCode(true);
      } else {
        setError(errorMessage(err));
      }
    } finally {
      setBusy(false);
    }
  }

  if (!picked && accounts.length > 0 && !another) {
    return (
      <div className="space-y-3">
        <h1 className="text-center text-sm text-muted-foreground">Choose an account</h1>
        <ul className="space-y-2">
          {accounts.map((a) => (
            <AccountRow key={a.email} account={a} onPick={() => pick(a)} />
          ))}
        </ul>
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground before:h-px before:flex-1 before:bg-line after:h-px after:flex-1 after:bg-line">
          or
        </div>
        <Button variant="ghost" className="w-full" onClick={() => setAnother(true)}>
          Use another account
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {picked ? (
        <div className="flex items-center gap-3 border-b border-line pb-3">
          <Avatar name={picked.name} size={30} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold">{picked.name}</span>
            <span className="block truncate text-xs text-muted-foreground">{picked.email}</span>
          </span>
          <button type="button" className="text-xs text-cyan-ink hover:underline" onClick={() => pick(null)}>
            Switch
          </button>
          {/* unseen: a password manager reads it to fill this account's password */}
          <input type="email" className="sr-only" tabIndex={-1} aria-hidden autoComplete="username" value={picked.email} readOnly />
        </div>
      ) : (
        <>
          <h1 className="text-center text-sm text-muted-foreground">Sign in</h1>
          <Input label="Email" type="email" autoComplete="email" autoFocus required value={email} onChange={(e) => setEmail(e.target.value)} />
        </>
      )}
      <Input
        label="Password"
        type="password"
        autoComplete="current-password"
        autoFocus={picked !== null}
        required
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      {needCode && (
        <Input
          label="Authenticator code"
          inputMode="numeric"
          autoComplete="one-time-code"
          autoFocus
          required
          value={code}
          onChange={(e) => setCode(e.target.value)}
        />
      )}
      {error && (
        <p role="alert" className="text-sm text-pink">
          {error}
        </p>
      )}
      <Button type="submit" className="w-full" disabled={busy}>
        Sign in
      </Button>
      {!picked && accounts.length > 0 && (
        <button type="button" className="block w-full text-center text-xs text-cyan-ink hover:underline" onClick={() => setAnother(false)}>
          ← Back to my accounts
        </button>
      )}
      <p className="text-center text-xs">
        <Link href={picked ? `/forgot?email=${encodeURIComponent(picked.email)}` : "/forgot"}>Forgot your password?</Link>
      </p>
    </form>
  );
}
