"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { NewPasswordForm } from "@/components/auth/NewPasswordForm";
import { api } from "@/lib/api";

export default function ResetPage() {
  const { token } = useParams<{ token: string }>();
  const [done, setDone] = useState(false);

  if (done) {
    return (
      <div className="space-y-4 text-sm">
        <p>Your password is updated, and you&apos;ve been signed out everywhere else.</p>
        <p>Your access tokens were revoked too: create new ones for your runners and link your agents to them.</p>
        <Link href="/login">Sign in</Link>
      </div>
    );
  }
  return (
    <NewPasswordForm
      submitLabel="Set new password"
      onSubmit={async (password) => {
        await api("/api/auth/reset", { method: "POST", json: { token, password } });
        setDone(true);
      }}
    >
      <h1 className="text-center text-sm text-muted-foreground">Choose a new password</h1>
    </NewPasswordForm>
  );
}
