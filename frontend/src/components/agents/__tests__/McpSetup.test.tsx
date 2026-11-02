import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { McpSetup } from "@/components/agents/McpSetup";

describe("McpSetup", () => {
  it("renders the Claude Code and Codex snippets with the current origin", () => {
    render(<McpSetup />);
    const origin = window.location.origin;
    expect(screen.getByLabelText("Claude Code command")).toHaveValue(
      `claude mcp add --transport http megoocolab ${origin}/api/mcp --header "Authorization: Bearer <your token>"`,
    );
    const codex = (screen.getByLabelText("Codex config") as HTMLTextAreaElement).value;
    expect(codex).toContain("[mcp_servers.megoocolab]");
    expect(codex).toContain(`url = "${origin}/api/mcp"`);
    expect(codex).toContain('bearer_token_env_var = "MEGOOCOLAB_TOKEN"');
  });

  it("shows the OMP config for ~/.omp/agent/mcp.json", () => {
    render(<McpSetup />);
    const origin = window.location.origin;
    const omp = JSON.parse((screen.getByLabelText("OMP config") as HTMLTextAreaElement).value);
    expect(omp).toEqual({
      mcpServers: { megoocolab: { type: "http", url: `${origin}/api/mcp`, headers: { Authorization: "Bearer <your token>" } } },
    });
    expect(screen.getAllByText(/~\/\.omp\/agent\/mcp\.json/).length).toBeGreaterThan(0);
  });
});
