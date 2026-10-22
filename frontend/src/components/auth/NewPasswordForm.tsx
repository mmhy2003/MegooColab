"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { errorMessage } from "@/lib/errors";

export const PASSWORD_MIN = 10;

/** New password + confirmation, checked client-side before `onSubmit` runs. */
export function NewPasswordForm({
  submitLabel,
  onSubmit,
  currentPassword = false,
  children,
}: {
  submitLabel: string;
  onSubmit: (password: string, current: string) => Promise<void>;
  currentPassword?: boolean;
  children?: React.ReactNode;
}) {
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handle(e: React.FormEvent) {
    e.preventDefault();
    if (password.length < PASSWORD_MIN) return setError(`Use at least ${PASSWORD_MIN} characters.`);
    if (password !== confirm) return setError("The two passwords don't match.");
    setBusy(true);
    setError(null);
    try {
      await onSubmit(password, current);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handle} className="space-y-4">
      {children}
      {currentPassword && (
        <Input label="Current password" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
      )}
      <Input label="New password" type="password" autoComplete="new-password" required minLength={PASSWORD_MIN} value={password} onChange={(e) => setPassword(e.target.value)} />
      <Input label="Confirm new password" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      {error && (
        <p role="alert" className="text-sm text-pink">
          {error}
        </p>
      )}
      <Button type="submit" className="w-full" disabled={busy}>
        {submitLabel}
      </Button>
    </form>
  );
}
