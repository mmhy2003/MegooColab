"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";

import { McpForm } from "@/components/hub/McpForm";
import { SecretsForm } from "@/components/hub/SecretsForm";
import { ShareEditor } from "@/components/hub/ShareEditor";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { hubKeys, useHubTool, type HubTool } from "@/lib/hub";
import { usePageTitle } from "@/lib/title";
import { useTrail } from "@/lib/trail";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="card space-y-3 p-4">
      <h2 className="text-sm font-bold">{title}</h2>
      {children}
    </section>
  );
}

function OwnerMcp({ tool }: { tool: HubTool }) {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: hubKeys.all });
  return (
    <>
      <Section title="Setup">
        <McpForm
          key={tool.rev}
          initial={tool}
          submitLabel="Save setup"
          onSubmit={async (body) => {
            await api(`/api/hub/tools/${tool.id}`, { method: "PATCH", json: body });
            await refresh();
          }}
        />
      </Section>
      <Section title="Secrets">
        <SecretsForm tool={tool} />
      </Section>
      <Section title="Sharing">
        <ShareEditor key={tool.rev} tool={tool} />
      </Section>
    </>
  );
}

export default function ToolPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const client = useQueryClient();
  const tool = useHubTool(id);
  const { ask, dialog } = useConfirm();
  usePageTitle(tool.data?.name, "Tool Hub");
  useTrail([{ label: "Tool Hub", href: "/hub" }, { label: tool.data?.name ?? null }]);

  if (tool.error) return <p role="alert" className="text-sm text-pink">{errorMessage(tool.error)}</p>;
  if (!tool.data) return null;
  const t = tool.data;
  const mine = t.sharing !== null && t.sharing !== undefined;

  return (
    <div className="max-w-3xl space-y-4">
      {dialog}
      <PageHeader
        title={t.name}
        subtitle={t.description || undefined}
        actions={
          mine && (
            <Button
              variant="danger"
              onClick={async () => {
                if (!(await ask({ tone: "danger", title: `Delete ${t.name}?`, text: "It leaves your library. Copies others took stay theirs.", ok: "Delete" }))) return;
                await api(`/api/hub/tools/${t.id}`, { method: "DELETE" });
                await client.invalidateQueries({ queryKey: hubKeys.all });
                router.push("/hub");
              }}
            >
              Delete
            </Button>
          )
        }
      />
      <div className="flex flex-wrap gap-2">
        {t.kind === "mcp" ? <Badge tone="cyan">MCP</Badge> : <Badge tone="pink">Skill</Badge>}
        <Badge>v{t.version}</Badge>
      </div>
      {mine && t.kind === "mcp" && t.can_edit && <OwnerMcp tool={t} />}
    </div>
  );
}
