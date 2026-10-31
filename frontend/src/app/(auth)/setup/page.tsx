"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { NewPasswordForm } from "@/components/auth/NewPasswordForm";
import { Input } from "@/components/ui/Input";
import { api } from "@/lib/api";
import { usePageTitle } from "@/lib/title";

export default function SetupPage() {
  usePageTitle("Set up");
  const router = useRouter();
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");

  useEffect(() => {
    api<{ needs_setup: boolean }>("/api/setup/status")
      .then((s) => !s.needs_setup && router.replace("/login"))
      .catch(() => undefined);
  }, [router]);

  return (
    <NewPasswordForm
      submitLabel="Create organization"
      onSubmit={async (password) => {
        await api("/api/setup", { method: "POST", json: { org_name: org, name, email, password } });
        router.push("/");
      }}
    >
      <h1 className="text-center text-sm text-muted-foreground">Welcome. Set up your organization and admin account.</h1>
      <Input label="Organization name" required value={org} onChange={(e) => setOrg(e.target.value)} />
      <Input label="Your name" required autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
      <Input label="Email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
    </NewPasswordForm>
  );
}
