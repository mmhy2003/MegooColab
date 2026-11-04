"use client";

import { SecretsPanel } from "@/components/secrets/SecretsPanel";
import { PageHeader } from "@/components/ui/PageHeader";
import { usePageTitle } from "@/lib/title";

export default function SecretsSettingsPage() {
  usePageTitle("Secrets");
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Secrets"
        subtitle="API keys, passwords and tokens your agents use as environment variables, never shown to them in a prompt."
      />
      <SecretsPanel base="/api/secrets" canEdit />
    </div>
  );
}
