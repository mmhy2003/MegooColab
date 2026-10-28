"use client";

import { Snippet } from "@/components/agents/Snippet";

export function McpSetup() {
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const claude = `claude mcp add --transport http megoocolab ${origin}/api/mcp --header "Authorization: Bearer <your token>"`;
  const codex = `[mcp_servers.megoocolab]\nurl = "${origin}/api/mcp"\nbearer_token_env_var = "MEGOOCOLAB_TOKEN"`;
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Let your coding tools read and update tasks. Create an access token with the MCP scope, then:
      </p>
      <Snippet label="Claude Code command" value={claude} />
      <div className="space-y-1">
        <Snippet label="Codex config" value={codex} />
        <p className="text-xs text-muted-foreground">
          Add this to <code>~/.codex/config.toml</code>, then set <code>MEGOOCOLAB_TOKEN</code> to your token in the environment.
        </p>
      </div>
    </div>
  );
}
