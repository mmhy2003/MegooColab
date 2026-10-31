"use client";

import { useParams, useRouter } from "next/navigation";

import { NewPasswordForm } from "@/components/auth/NewPasswordForm";
import { api } from "@/lib/api";
import { usePageTitle } from "@/lib/title";

export default function InvitePage() {
  usePageTitle("Accept invitation");
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  return (
    <NewPasswordForm
      submitLabel="Join"
      onSubmit={async (password) => {
        await api("/api/auth/accept-invite", { method: "POST", json: { token, password } });
        router.push("/");
      }}
    >
      <h1 className="text-center text-sm text-muted-foreground">You&apos;re invited. Choose a password to join.</h1>
    </NewPasswordForm>
  );
}
