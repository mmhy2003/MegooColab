"use client";

import { Suspense } from "react";

import { DreamingSchedule } from "@/components/ai/DreamingSchedule";
import { JobModels } from "@/components/ai/JobModels";
import { ProviderList } from "@/components/ai/ProviderList";
import { UsageTable } from "@/components/ai/UsageTable";
import { DreamPanel } from "@/components/memory/DreamPanel";
import { PageHeader } from "@/components/ui/PageHeader";
import { TabPanel, Tabs, useTabParam } from "@/components/ui/Tabs";
import { useAdminSettings } from "@/lib/adminSettings";
import { useMe } from "@/lib/me";

const TABS = [
  { id: "providers", label: "Providers" },
  { id: "models", label: "Models per job" },
  { id: "dreaming", label: "Dreaming" },
  { id: "usage", label: "Usage" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function AiTabs() {
  const [tab, setTab] = useTabParam<TabId>(TABS.map((t) => t.id));
  const settings = useAdminSettings();
  return (
    <div className="max-w-4xl">
      <PageHeader
        title="AI"
        subtitle="Model providers, the model each AI job uses, nightly dreaming, and what the calls cost. Keys are stored encrypted."
      />
      <Tabs label="AI sections" tabs={TABS} value={tab} onChange={setTab} />
      <TabPanel id="providers" active={tab === "providers"}><ProviderList /></TabPanel>
      <TabPanel id="models" active={tab === "models"}><JobModels /></TabPanel>
      <TabPanel id="dreaming" active={tab === "dreaming"}>
        <div className="space-y-4">
          {settings.data && <DreamingSchedule settings={settings.data} />}
          <DreamPanel />
        </div>
      </TabPanel>
      <TabPanel id="usage" active={tab === "usage"}><UsageTable /></TabPanel>
    </div>
  );
}

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
    <Suspense>
      <AiTabs />
    </Suspense>
  );
}
