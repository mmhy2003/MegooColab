`megoocolab-runner` 0.10.1 gives Claude Code agents the MCP servers you set up in the Tool Hub, as OMP and Codex agents already had.

## Update

- **Windows (Scoop):** stop the service first, then update and start it again:
  `megoocolab-runner service stop; scoop update megoocolab-runner; megoocolab-runner service start`
- **macOS and Linux:** run the install command again: `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`, then restart the service if it runs as one: `megoocolab-runner service stop && megoocolab-runner service start`.

## Fixed

- **Claude Code agents now see the Tool Hub's MCP servers.** Claude Code runs start without your personal Claude settings, so they don't leak into runs, and that also meant they loaded none of the MCP servers in `~/.claude.json`, the hub's included. The runner now hands each Claude Code run the hub's servers itself, when a session starts, is resumed or is reloaded.
  - A read-only run gets only the servers marked safe for read-only runs, as with OMP.
  - Servers you added to `~/.claude.json` by hand still don't reach runs. Bring one into the Tool Hub with import or **Take over** to share it with your agents.
  - Codex agents are unchanged: Codex loads the hub's servers from its own `config.toml` in every run.

Runner 0.10.1 works with any MegooColab server.
