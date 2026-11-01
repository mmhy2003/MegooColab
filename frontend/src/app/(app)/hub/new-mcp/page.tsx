"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { McpForm } from "@/components/hub/McpForm";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { hubKeys, type HubTool } from "@/lib/hub";
import { usePageTitle } from "@/lib/title";

export default function NewMcpPage() {
  usePageTitle("Add MCP", "Tool Hub");
  const router = useRouter();
  const client = useQueryClient();
  return (
    <div className="max-w-3xl">
      <PageHeader title="Add MCP" subtitle="Set it up once. You add its secrets on the next page; they are stored encrypted." />
      <div className="card p-4">
        <McpForm
          submitLabel="Add MCP"
          onSubmit={async (body) => {
            const tool = await api<HubTool>("/api/hub/tools", { method: "POST", json: { kind: "mcp", ...body } });
            await client.invalidateQueries({ queryKey: hubKeys.all });
            router.push(`/hub/${tool.id}`);
          }}
        />
      </div>
    </div>
  );
}
