"use client";

import { useRouter } from "next/navigation";

import { NewPasswordForm } from "@/components/auth/NewPasswordForm";
import { api } from "@/lib/api";

export default function ChangePasswordPage() {
  const router = useRouter();
  return (
    <NewPasswordForm
      currentPassword
      submitLabel="Change password"
      onSubmit={async (password, current) => {
        await api("/api/auth/change-password", {
          method: "POST",
          json: { current_password: current, new_password: password },
        });
        router.push("/");
      }}
    >
      <h1 className="text-center text-sm text-muted-foreground">Choose your own password to continue.</h1>
    </NewPasswordForm>
  );
}
