`megoocolab-runner` 0.6.0 hands **images** to agents, and lets a second agent on the same machine review a task's pull request. MegooColab 0.10.0 uses both.

## Update

- **Windows (Scoop):** stop the service first, then update and start it again:
  `megoocolab-runner service stop; scoop update megoocolab-runner; megoocolab-runner service start`
- **macOS and Linux:** run the install command again: `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`, then restart the service if it runs as one: `megoocolab-runner service stop && megoocolab-runner service start`.

## New

- **Images reach the agent.** For a run or a message sent to a running agent (a steer), the runner downloads the images that came with it from MegooColab, using its own runner token.
  - When the agent program says it takes images in its prompt, they go into the prompt itself, like a pasted screenshot.
  - Otherwise they are saved in a folder for the run that the agent may read, and the prompt names them. The folder is removed when the run ends.
- **Tells MegooColab it takes images** (`images/1`), so people can send images to its agents. With an older runner, the image button explains that the runner needs updating.

## Improved

- **A second agent can work on the same task branch on one machine.** When a pull request's reviewer is another agent on the same clone as the task's agent, git allows only one checkout of the task's branch. The reviewer now gets its own worktree, detached at the branch's latest commit, instead of failing to start.

Runner 0.6.0 also works with older MegooColab servers, which simply send no images.
