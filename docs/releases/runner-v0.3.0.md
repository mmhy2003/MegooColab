`megoocolab-runner` 0.3.0 passes people's messages to an agent while it works, without stopping it. MegooColab 0.7.0 uses it for messages sent to an agent from a task or a chat.

## Update

- **Windows (Scoop):** stop the service first, then update and start it again:
  `megoocolab-runner service stop; scoop update megoocolab-runner; megoocolab-runner service start`
- **macOS and Linux:** run the install command again: `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`, then restart the service if it runs as one: `megoocolab-runner service stop && megoocolab-runner service start`.

## New

- **Messages while the agent works.** A message sent to the agent reaches it in the turn it is working on, through the steering request that the Claude Code and Codex adapters support. If the model is mid-reply, the agent breaks off and reads the message. A command or tool it is running carries on.
- **Held until the agent is ready.** A message that arrives while the session is still starting is held, then passed on once the agent is working on its turn. Several messages are passed on in the order they were sent.
- **Nothing lost.** When there is no turn to pass a message into, or the adapter can't take one, the runner tells MegooColab, which gives the message to the agent's next run instead. This happens when a turn has just ended, or with an older adapter.

Runner 0.3.0 also works with older MegooColab servers, which simply don't send messages mid-run.
