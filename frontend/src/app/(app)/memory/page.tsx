"use client";

import { AskMemory } from "@/components/memory/AskMemory";
import { EntityList } from "@/components/memory/EntityList";
import { ProductEditor } from "@/components/memory/ProductEditor";
import { PageHeader } from "@/components/ui/PageHeader";
import { canManage, useMe } from "@/lib/me";
import { useMemEntities } from "@/lib/memory";

export default function MemoryPage() {
  const { data: me } = useMe();
  const entities = useMemEntities();
  return (
    <div className="space-y-6">
      <PageHeader
        title="Memory"
        subtitle="What the organization has learned from tasks, agent runs, reviews and the Knowledge Base. Every conclusion links to its source; correct or delete anything that is wrong."
      />
      <AskMemory />
      {canManage(me) && <ProductEditor />}
      {entities.data && <EntityList entities={entities.data} />}
    </div>
  );
}
