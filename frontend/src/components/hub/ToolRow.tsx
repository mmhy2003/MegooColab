import Link from "next/link";

import { Badge } from "@/components/ui/Badge";
import { sharingLabel, type HubToolSummary } from "@/lib/hub";

/** One tool on a Tool Hub shelf. On "Mine" it shows the tool's state; elsewhere, whose it is. */
export function ToolRow({ tool, mine }: { tool: HubToolSummary; mine: boolean }) {
  return (
    <li>
      <Link href={`/hub/${tool.id}`} className="card block p-3 no-underline hover:border-cyan">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-bold text-fg">{tool.name}</span>
          {tool.kind === "mcp" ? <Badge tone="cyan">MCP</Badge> : <Badge tone="pink">Skill</Badge>}
          <span className="flex-1" />
          {mine ? (
            <>
              {tool.removed && <Badge tone="pink">removed by an admin</Badge>}
              {tool.secrets_missing && <Badge tone="amber">key missing</Badge>}
              {tool.source_state === "update_available" && <Badge tone="cyan">Update available</Badge>}
              {tool.source_state === "no_longer_shared" && <Badge>no longer shared</Badge>}
              <span className="text-xs text-muted-foreground">{sharingLabel(tool.sharing)}</span>
            </>
          ) : (
            <span className="text-xs text-muted-foreground">by {tool.owner.name}</span>
          )}
        </div>
        {tool.description && <p className="mt-1 text-sm text-muted-foreground">{tool.description}</p>}
      </Link>
    </li>
  );
}
