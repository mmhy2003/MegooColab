"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";

export default function ForgotPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (sent) {
    return (
      <div className="space-y-4 text-sm">
        <p>If that email has an account, a reset link is on its way. It works for 1 hour.</p>
        <p className="text-muted">No email? Your admin can give you a reset link directly.</p>
        <Link href="/login">Back to sign in</Link>
      </div>
    );
  }
  return (
    <form
      className="space-y-4"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await api("/api/auth/forgot", { method: "POST", json: { email } });
          setSent(true);
        } catch (err) {
          setError(errorMessage(err));
        }
      }}
    >
      <h1 className="text-center text-sm text-muted">Reset your password</h1>
      <Input label="Email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      <Button type="submit" className="w-full">Send reset link</Button>
      <p className="text-center text-xs">
        <Link href="/login">Back to sign in</Link>
      </p>
    </form>
  );
}
