`megoocolab-runner` 0.5.0 runs **OMP** (Oh My Pi) agents, alongside Claude Code and Codex. MegooColab 0.9.0 uses it for OMP agents and their Tool Hub tools.

## Update

- **Windows (Scoop):** stop the service first, then update and start it again:
  `megoocolab-runner service stop; scoop update megoocolab-runner; megoocolab-runner service start`
- **macOS and Linux:** run the install command again: `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`, then restart the service if it runs as one: `megoocolab-runner service stop && megoocolab-runner service start`.

## New

- **Starts OMP agents** with `omp acp`, using your own OMP setup, models and sign-ins on the machine. It needs OMP 18.12.6 or newer:
  - Windows: `irm https://omp.sh/install.ps1 | iex`
  - macOS and Linux: `curl -fsSL https://omp.sh/install | sh`
  - then sign in to your model providers with `omp auth-broker login`.
- **Says what's missing.** An OMP agent reports **omp not found**, **OMP 18.12.6 or newer is needed**, or **omp found but cannot be started; reinstall with the OMP installer**, instead of failing its runs.
- **Asks before OMP acts.** OMP runs with its approval mode set to `write`: the runner decides on every command, delete and move, and OMP's file edits go through the runner, so read-only runs stay read-only.
- **Tool Hub for OMP.** Pushed MCP servers go into OMP's `mcp.json` and skills into its `skills/` folder, in the active OMP agent folder (it follows `omp config path`, OMP profiles and `PI_CODING_AGENT_DIR`). As for Claude Code and Codex, only the runner's own entries are ever touched.
- **OMP runs get their hub MCP servers** directly, since OMP ignores its own MCP config when run by the runner: every hub server in workspace runs, and only those safe in read-only runs while brainstorming, planning or reviewing.
- **`megoocolab-runner doctor`** checks OMP: whether it is installed, its version, and how to install it.
- `MEGOO_ADAPTER_OMP` replaces the OMP command line, as the other programs' overrides do.

Runner 0.5.0 also works with older MegooColab servers, which simply don't send OMP runs.
