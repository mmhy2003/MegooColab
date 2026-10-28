"use client";

import { Suspense } from "react";

import { PageHeader } from "@/components/ui/PageHeader";
import { useTabParam } from "@/components/ui/Tabs";
import { METHODOLOGY_STAGES, MethodologyEditor } from "@/components/workflow/MethodologyEditor";
import { useMe } from "@/lib/me";

export default function AdminMethodologyPage() {
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
    <div>
      <PageHeader
        title="Methodology"
        subtitle="The instructions agents follow at each workflow stage. Every save creates a new version; runs record the version they used."
      />
      <Suspense>
        <StageTabs />
      </Suspense>
    </div>
  );
}

function StageTabs() {
  const [stage, setStage] = useTabParam(METHODOLOGY_STAGES);
  return <MethodologyEditor stage={stage} onStage={setStage} />;
}
