"use client";

import { JobModels } from "@/components/ai/JobModels";
import { ProviderList } from "@/components/ai/ProviderList";
import { UsageTable } from "@/components/ai/UsageTable";
import { DreamPanel } from "@/components/memory/DreamPanel";
import { PageHeader } from "@/components/ui/PageHeader";
import { useMe } from "@/lib/me";

export default function AdminAiPage() {
  const { data: me } = useMe();
  if (!me) return null;
  if (me.role !== "admin") {
    return (
      <div className="card mx-auto mt-10 max-w-md p-6 text-center">
        <p className="text-pink">You don&apos;t have permission to do that.</p>
      </div>
    );
  }
  return (
    <div className="max-w-4xl space-y-4">
      <PageHeader
        title="AI"
        subtitle="Model providers, the model each AI job uses, and what the calls cost. Keys are stored encrypted."
      />
      <ProviderList />
      <JobModels />
      <DreamPanel />
      <UsageTable />
    </div>
  );
}
