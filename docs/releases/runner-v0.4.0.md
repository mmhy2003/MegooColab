`megoocolab-runner` 0.4.0 installs your Tool Hub's MCP servers and skills on your machine, for Claude Code and Codex. MegooColab 0.8.0 uses it for **Push** and **Import from this machine** on **Settings › My agents**.

## Update

- **Windows (Scoop):** stop the service first, then update and start it again:
  `megoocolab-runner service stop; scoop update megoocolab-runner; megoocolab-runner service start`
- **macOS and Linux:** run the install command again: `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`, then restart the service if it runs as one: `megoocolab-runner service stop && megoocolab-runner service start`.

## New

- **Installs pushed tools at user level** for the agent programs linked to the machine:
  - Claude Code: MCP servers in `~/.claude.json`, skills in `~/.claude/skills/`;
  - Codex: MCP servers as `[mcp_servers.<name>]` in `config.toml` (`$CODEX_HOME`, else `~/.codex`), skills in `~/.agents/skills/`.
  So your own Claude Code and Codex on that machine get them too.
- **Only touches its own entries.** The runner keeps a record of what it installed and never edits or removes anything else. Every other key of `~/.claude.json`, and every other line of `config.toml`, comments included, stays as it was. An entry you made by hand with the same name is left alone until you choose **Take over**.
- **Keys stay private.** Files that hold keys are written all at once and readable by you alone (owner-only on macOS and Linux, a user-only access rule on Windows). A failure report never quotes a value.
- **Works on Windows, macOS and Linux.** On Windows, `npx`-style launchers are started through `cmd /c`.
- **Reports hand edits.** When it reconnects, the runner tells MegooColab which installed tools were changed or deleted by hand.
- **Import.** On request, it lists the MCP servers and skills you set up by hand in Claude Code and Codex, without changing anything.
- **Agents use them.** Hub skills reach Claude Code runs as a small local plugin, so agents get exactly the hub's skills without your personal settings. MCP servers marked safe in read-only runs are allowed in brainstorm, plan and review runs.

## Improved

- The runner accepts larger messages from the server (64 MiB), so pushes with several skills arrive whole.

Runner 0.4.0 also works with older MegooColab servers, which simply don't send pushes.
