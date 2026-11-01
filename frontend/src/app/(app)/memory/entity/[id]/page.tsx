"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { ConclusionList } from "@/components/memory/ConclusionList";
import { EntitySidebar } from "@/components/memory/EntitySidebar";
import { BackLink } from "@/components/nav/BackLink";
import { SideListLayout } from "@/components/nav/SideListLayout";
import { Button } from "@/components/ui/Button";
import { Markdown } from "@/components/ui/Markdown";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { canManage, useMe } from "@/lib/me";
import { ENTITY_GROUPS, memKeys, useMemEntities, useMemEntity } from "@/lib/memory";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { usePageTitle } from "@/lib/title";
import { useTrail } from "@/lib/trail";

export default function MemoryEntityPage() {
  const { ask, dialog } = useConfirm();
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const client = useQueryClient();
  const { data: me } = useMe();
  const detail = useMemEntity(id);
  // the list beside it is loaded already: it names the entity while its own page loads
  const listed = useMemEntities().data?.find((e) => e.id === id);
  const known = detail.data?.entity ?? listed;
  usePageTitle(known?.name, "Memory");
  const group = known ? (ENTITY_GROUPS.find((g) => g.kind === known.kind)?.label ?? known.kind) : null;
  useTrail([{ label: "Memory", href: "/memory" }, { label: group }, { label: known?.name ?? null }]);
  const shell = (content: React.ReactNode) => (
    <div className="space-y-4">
      <BackLink area="memory-read" fallback={{ href: "/memory", label: "Memory" }} />
      <SideListLayout sideLabel="Entities" side={<EntitySidebar currentId={id} />}>
        {content}
      </SideListLayout>
    </div>
  );

  if (detail.error) {
    return (
      <div className="card mx-auto mt-10 max-w-md p-6 text-center">
        <p className="text-pink">{errorMessage(detail.error)}</p>
        <Link href="/memory">Back to Memory</Link>
      </div>
    );
  }
  if (!detail.data) {
    const loading = <p className="text-sm text-muted-foreground">Loading…</p>;
    return listed ? shell(loading) : loading;
  }
  const { entity, cards } = detail.data;

  return (
    <>
      <div className="space-y-4">
        <BackLink area="memory-read" fallback={{ href: "/memory", label: "Memory" }} />
        <SideListLayout sideLabel="Entities" side={<EntitySidebar currentId={entity.id} />}>
          <PageHeader
            title={entity.name}
            subtitle={entity.description || group || undefined}
            actions={
              entity.kind === "product" &&
              canManage(me) && (
                <Button
                  variant="danger"
                  onClick={async () => {
                    if (!(await ask({ tone: "danger", title: `Delete product ${entity.name}?`, text: "Its conclusions are deleted too.", ok: "Delete" }))) return;
                    await api(`/api/memory/products/${entity.id}`, { method: "DELETE" });
                    await client.invalidateQueries({ queryKey: memKeys.all });
                    router.push("/memory");
                  }}
                >
                  Delete product
                </Button>
              )
            }
          />
          <section aria-label="Summary cards" className="space-y-3">
            {cards.length === 0 && (
              <p className="text-sm text-muted-foreground">No summary yet. Summaries are written when the memory dreams (nightly).</p>
            )}
            {cards.map((c) => (
              <div key={`${c.scope.kind}-${c.scope.id}`} className="card p-4">
                <p className="mb-2 text-xs text-muted-foreground">
                  {c.scope.name} · updated {new Date(c.refreshed_at).toLocaleDateString()}
                </p>
                <div className="kb-prose">
                  <Markdown>{c.summary_md}</Markdown>
                </div>
              </div>
            ))}
          </section>
          <ConclusionList entityId={entity.id} />
        </SideListLayout>
      </div>
      {dialog}
    </>
  );
}
