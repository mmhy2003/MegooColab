"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { hubKeys, type HubAdminTool } from "@/lib/hub";
import { useMe } from "@/lib/me";
import { usePageTitle } from "@/lib/title";

function sharedWith(t: HubAdminTool): string {
  const names = [...t.sharing.teams, ...t.sharing.users].map((x) => x.name);
  return [...(t.sharing.everyone ? ["Everyone"] : []), ...names].join(", ");
}

function SharedTools() {
  const client = useQueryClient();
  const { ask, dialog } = useConfirm();
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const tools = useQuery({
    queryKey: hubKeys.admin(q.trim()),
    queryFn: () => api<HubAdminTool[]>(`/api/admin/hub/tools${q.trim() ? `?${new URLSearchParams({ q: q.trim() })}` : ""}`),
  });
  const act = async (t: HubAdminTool, path: "unshare" | "remove") => {
    setError(null);
    try {
      await api(`/api/admin/hub/tools/${t.id}/${path}`, { method: "POST" });
      await client.invalidateQueries({ queryKey: hubKeys.all });
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  return (
    <div className="space-y-3">
      {dialog}
      <input
        type="search"
        aria-label="Search shared tools"
        placeholder="Search shared tools…"
        value={q}
        maxLength={200}
        onChange={(e) => setQ(e.target.value)}
        className="w-full rounded border border-line bg-surface-2 px-2 py-1.5 text-sm text-fg placeholder:text-muted-foreground focus:border-cyan focus:outline-none"
      />
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      {tools.error && <p role="alert" className="text-sm text-pink">{errorMessage(tools.error)}</p>}
      {tools.data?.length === 0 && <p className="text-sm text-muted-foreground">Nothing is shared beyond its owner.</p>}
      <ul className="space-y-2">
        {tools.data?.map((t) => (
          <li key={t.id} className="card flex flex-wrap items-center gap-2 p-3">
            <span className="font-bold">{t.name}</span>
            {t.kind === "mcp" ? <Badge tone="cyan">MCP</Badge> : <Badge tone="pink">Skill</Badge>}
            <span className="text-xs text-muted-foreground">by {t.owner.name}</span>
            <span className="flex-1 text-xs text-muted-foreground">{sharedWith(t)}</span>
            <Button
              variant="ghost"
              aria-label={`Stop sharing ${t.name}`}
              onClick={async () => {
                const text = "It goes back to its owner only. Copies already taken stay.";
                if (await ask({ tone: "warn", title: `Stop sharing ${t.name}?`, text, ok: "Stop sharing" })) await act(t, "unshare");
              }}
            >
              Stop sharing
            </Button>
            <Button
              variant="danger"
              aria-label={`Remove ${t.name}`}
              onClick={async () => {
                const text = "Everyone who added it sees “removed by an admin”. Nothing changes on their machines until they push.";
                if (await ask({ tone: "danger", title: `Remove ${t.name}?`, text, ok: "Remove" })) await act(t, "remove");
              }}
            >
              Remove
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function AdminHubPage() {
  usePageTitle("Tool Hub", "Admin");
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
        title="Tool Hub"
        subtitle="Tools people share beyond themselves. Their secrets are never shown, and private tools aren't listed."
      />
      <SharedTools />
    </div>
  );
}
