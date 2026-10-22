"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ApiError, api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";

/** Only same-site paths are honoured, so a crafted link can't bounce users off-site. */
export function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/projects";
}

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
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

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/auth/login", {
        method: "POST",
        json: { email, password, totp_code: needCode ? code : undefined },
      });
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

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <h1 className="text-center text-sm text-muted">Sign in</h1>
      <Input label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      <Input label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
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
      <p className="text-center text-xs">
        <Link href="/forgot">Forgot your password?</Link>
      </p>
    </form>
  );
}
