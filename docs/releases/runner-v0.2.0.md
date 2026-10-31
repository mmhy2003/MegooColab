`megoocolab-runner` 0.2.0 starts each agent on the model and thinking effort chosen for it in MegooColab. MegooColab 0.4.0 needs it for that.

## Update

- **Windows (Scoop):** `scoop update megoocolab-runner`
- **macOS and Linux:** run the install command again: `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`

If it runs as a service, restart it afterwards: `megoocolab-runner service stop`, then `service start`.

## New

- **The chosen model and effort.** Each run starts on the agent's model and effort from **My agents**. A model can be given by its id or its name ("Opus 5.5", "gpt-6.1-sol"), whatever the case and spacing.
- **No silent substitutes.** If Claude Code or Codex doesn't offer the chosen model, or the model doesn't have the chosen effort level, the run stops before the agent starts work, and MegooColab says why. Codex accepts any model name without complaint, so the runner also checks that the model is one Codex lists.
- **The models on offer.** Each run tells MegooColab which models the agent offers and each model's effort levels, so you can pick from them on **My agents**, and which model and effort the run used.
- To learn every model's effort levels, the runner goes through the models once, on each program's first run after it starts. That run takes a few seconds longer.

Runner 0.2.0 also works with older MegooColab servers: it then uses each program's own default model, as before.
