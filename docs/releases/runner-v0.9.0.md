`megoocolab-runner` 0.9.0 starts each workflow run on the model and effort its stage asks for, even when the run continues an earlier session.

## Update

- **Windows (Scoop):** stop the service first, then update and start it again:
  `megoocolab-runner service stop; scoop update megoocolab-runner; megoocolab-runner service start`
- **macOS and Linux:** run the install command again: `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`, then restart the service if it runs as one: `megoocolab-runner service stop && megoocolab-runner service start`.

## New

- **A run can carry its own model and effort.** With MegooColab 0.20.0 and later, a stage that has a model of its own (Agents → the agent → Model by stage) sends it with each run, and the runner puts the agent's session on that model and effort.
  - **Continued sessions switch too.** A session an earlier stage put on another model goes back to the agent's own when the next stage asks for it. To know what "the program's own model" is, the runner notes the model each program starts a new session on and keeps it in its cache, so it survives a restart.
  - **Until it knows,** a run that has to go back to the program's own model starts a new session instead of continuing the old one, with everything the continued session would have been told. This can happen once per program after updating.
  - A stage with a model but no effort runs on that model's own default effort.
  - Programs that offer no model list keep continuing their sessions as before.

The runner works with any MegooColab server: an older server never sends a run its own model, and runs use the agent's model as before.
