"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { ConclusionList } from "@/components/memory/ConclusionList";
import { Button } from "@/components/ui/Button";
import { Markdown } from "@/components/ui/Markdown";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { canManage, useMe } from "@/lib/me";
import { ENTITY_GROUPS, memKeys, useMemEntity } from "@/lib/memory";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { usePageTitle } from "@/lib/title";

export default function MemoryEntityPage() {
  const { ask, dialog } = useConfirm();
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const client = useQueryClient();
  const { data: me } = useMe();
  const detail = useMemEntity(id);
  usePageTitle(detail.data?.entity.name, "Memory");

  if (detail.error) {
    return (
      <div className="card mx-auto mt-10 max-w-md p-6 text-center">
        <p className="text-pink">{errorMessage(detail.error)}</p>
        <Link href="/memory">Back to Memory</Link>
      </div>
    );
  }
  if (!detail.data) return <p className="text-sm text-muted-foreground">Loading…</p>;
  const { entity, cards } = detail.data;
  const kind = ENTITY_GROUPS.find((g) => g.kind === entity.kind)?.label ?? entity.kind;

  return (
    <>
      <div className="space-y-6">
        <p className="text-sm">
          <Link href="/memory">Memory</Link>
        </p>
        <PageHeader
          title={entity.name}
          subtitle={entity.description || kind}
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
      </div>
      {dialog}
    </>
  );
}
