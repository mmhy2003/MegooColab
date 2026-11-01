"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { McpForm } from "@/components/hub/McpForm";
import { SecretsForm } from "@/components/hub/SecretsForm";
import { SetupText, SharedToolView } from "@/components/hub/SharedToolView";
import { ShareEditor } from "@/components/hub/ShareEditor";
import { SkillFiles } from "@/components/hub/SkillFiles";
import { SkillUpload } from "@/components/hub/SkillUpload";
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

function useRefresh() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: hubKeys.all });
}

/** The one switch a copy keeps for its owner. */
function ReadOnlySwitch({ tool }: { tool: HubTool }) {
  const refresh = useRefresh();
  const [error, setError] = useState<string | null>(null);
  return (
    <div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={tool.read_only_safe}
          onChange={async (e) => {
            setError(null);
            try {
              await api(`/api/hub/tools/${tool.id}`, { method: "PATCH", json: { read_only_safe: e.target.checked } });
              await refresh();
            } catch (err) {
              setError(errorMessage(err));
            }
          }}
        />
        Safe in read-only runs
      </label>
      <p className="mt-1 text-xs text-muted-foreground">Turn this on only for tools that read and never change anything outside.</p>
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
    </div>
  );
}

function OwnTool({ tool }: { tool: HubTool }) {
  const refresh = useRefresh();
  return (
    <>
      {tool.kind === "mcp" ? (
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
      ) : (
        <Section title="Files">
          <SkillFiles tool={tool} />
          <SkillUpload toolId={tool.id} onDone={() => refresh()} />
        </Section>
      )}
      {tool.kind === "mcp" && (
        <Section title="Secrets">
          <SecretsForm tool={tool} />
        </Section>
      )}
      <Section title="Sharing">
        <ShareEditor key={tool.rev} tool={tool} />
      </Section>
    </>
  );
}

function CopyOfTool({ tool }: { tool: HubTool }) {
  const refresh = useRefresh();
  const { ask, dialog } = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const call = async (path: string) => {
    setError(null);
    try {
      await api(`/api/hub/tools/${tool.id}/${path}`, { method: "POST" });
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  const from = tool.source?.owner_name;
  return (
    <>
      {dialog}
      <Section title="Copy">
        <p className="text-sm">
          {tool.source
            ? `Copy of ${tool.source.name} by ${tool.source.owner_name} · v${tool.version}`
            : "Copy · no longer shared"}
        </p>
        <div className="flex flex-wrap gap-2">
          {tool.source_state === "update_available" && <Button onClick={() => call("update")}>Take update</Button>}
          <Button
            variant="ghost"
            onClick={async () => {
              const text = from ? `It stops getting updates from ${from}.` : "It stops being a copy.";
              if (await ask({ tone: "warn", title: `Make ${tool.name} your own?`, text, ok: "Make it my own" })) await call("own");
            }}
          >
            Make it my own
          </Button>
        </div>
        {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      </Section>
      <Section title={tool.kind === "mcp" ? "Setup" : "Files"}>
        {tool.spec ? <SetupText spec={tool.spec} /> : <SkillFiles tool={tool} />}
        <ReadOnlySwitch tool={tool} />
      </Section>
      {tool.kind === "mcp" && (
        <Section title="Secrets">
          <SecretsForm tool={tool} />
        </Section>
      )}
    </>
  );
}

export default function ToolPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const refresh = useRefresh();
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
                const text = "It leaves your library. Copies others took stay theirs.";
                if (!(await ask({ tone: "danger", title: `Delete ${t.name}?`, text, ok: "Delete" }))) return;
                await api(`/api/hub/tools/${t.id}`, { method: "DELETE" });
                await refresh();
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
        {t.secrets_missing && <Badge tone="amber">key missing</Badge>}
        {t.source_state === "update_available" && <Badge tone="cyan">Update available</Badge>}
        {t.source_state === "no_longer_shared" && <Badge>no longer shared</Badge>}
      </div>
      {!mine ? (
        <SharedToolView tool={t} />
      ) : t.removed ? (
        <p role="status" className="card border-pink p-4 text-sm text-pink">
          removed by an admin. You can only delete it.
        </p>
      ) : t.is_copy ? (
        <CopyOfTool tool={t} />
      ) : (
        <OwnTool tool={t} />
      )}
    </div>
  );
}
