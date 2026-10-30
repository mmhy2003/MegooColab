A small fix release for `megoocolab-runner`.

## Update

- **Windows (Scoop):** `scoop update megoocolab-runner`
- **macOS and Linux:** run the install command again: `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`

If it runs as a service, restart it afterwards: `megoocolab-runner service stop`, then `service start`.

## Fixed

- **Status reports right after connecting.** An agent's status report sent in the instant after the runner connected could fail with "not connected" and be lost. It now waits that instant out and is delivered.

## Improved

- **One token per computer.** The README now explains this setup, which MegooColab 0.2.0 introduces: link each agent to its computer's token, and each computer's runner can be online at the same time.
