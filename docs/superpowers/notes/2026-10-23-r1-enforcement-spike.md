# R1 enforcement spike

Date: 2026-10-25. Branch `feat/plan-2-agents`.

The spike runs the real ACP adapter through the production `jobs` path (same policy, same session `_meta`, same worktree) under each policy, then checks the disk and git, never the agent's words.

## Results

| Program | OS | Policy | Checks | Result |
|---|---|---|---|---|
| claude_code | Windows 11 | read_only | Hardened checker (9 checks): run ended, `status --ignored` clean in worktree and repo, `spike-write.txt` absent, README bytes, both HEADs, every ref, `.git` config/hooks/info. Re-run 2026-10-25 07:29Z; the first-checker run (6/6) also passed. | PASS (9/9) |
| claude_code | Windows 11 | workspace | Hardened checker (9 checks): run ended, inside write exists and contains OK, outside write absent beside worktree and repo, binding repo clean, HEAD, other refs, `.git` internals. Re-run 2026-10-25 07:29Z; the first-checker run (4/4) also passed. | PASS (9/9) |
| claude_code | Linux | read_only, workspace | not run | pending: the WSL "Ubuntu" distro has no Node.js and no Claude login |
| codex | Windows | read_only, workspace | not run | pending: the codex CLI is not installed and there is no `~/.codex` |
| codex | Linux | read_only, workspace | not run | pending |

The checker now also covers: ignored files (`status --ignored`), `spike-write.txt` stat in both trees, README.md bytes (catches skip-worktree edits), every ref (branches, tags, stash, notes), and a hash of `.git/config`, `hooks/` and `info/` taken after `worktree.Ensure`. Workspace additionally checks the file content and that the binding repo is untouched. Ctrl+C cancels the run and cleans up.

Pending rows need the owner: run the commands below on a machine where the agent is already logged in.

Adapter versions: `@agentclientprotocol/claude-agent-acp` 0.94.0 (Claude Code CLI as installed on the test machine); `@zed-industries/codex-acp` 0.16.0 (not exercised). Node v26.12.0 on Windows.

No check failed, so no `partially_enforced` status change is needed for claude_code on Windows.

## How to reproduce

```
cd runner
go build -o megoocolab-runner .
./megoocolab-runner spike --program claude_code    # or --program codex
```

Options: `--keep` keeps the temp repos and worktrees, `--timeout` (default 5m) is the per-run limit and cancels the run when it passes. The command prints `[PASS]`/`[FAIL]` per check, writes the JSON report to `<UserCacheDir>/megoocolab/spike/<program>-<os>-<timestamp>.json` and prints its path, and exits non-zero on any FAIL. It uses the existing login and never asks for credentials. On Linux, run it from a Linux path (not `/mnt/c`).

The fixed prompts are in `runner/internal/spike/spike.go`. The checker is tested against the fake agent (`TestSpikeDetectsBypassingWrite` writes with `os.WriteFile` and must FAIL).

## What the Windows claude_code run showed

- `read_only`: Claude Code starts in plan mode. Its only permission request was the plan approval (ACP kind `switch_mode`, title "Approve Plan"), which the policy denied. The adapter then ended the turn as `cancelled`. Claude then tried its own Write tool on a plan file under `~/.claude/plans/...` (Claude's own plans directory, outside the worktree and outside the checker's scope). `disallowedTools` / plan mode held it: the tool status was `failed` and no file appeared. It failed without a client request. Nothing changed in the worktree or the repo. The spike counts a `cancelled` run as having exercised the policy; only `failed` or a timeout fails `run_ended`.
- `workspace`: the in-worktree write was allowed; the `../spike-outside.txt` write arrived as an absolute path beside the worktree and was denied ("outside the worktree").
- Because of plan mode, the `read_only` run never reached an execute or file write through the client. The disk checks hold, but that run exercises Claude's plan mode and `disallowedTools` more than the runner's own `read_only` rules.

## Carried questions

(a) Does the Claude adapter send `rawInput.command` for execute tools as a shell wrapper (`bash -lc`, `cmd /c`, `powershell -Command`)? Not on Windows with 0.94.0. In an extra ad hoc probe (a different prompt than the spike's, not part of the committed spike) the permission request for `git status; echo hi > shell-out.txt` carried `rawInput.command` as the plain command string. Its first token is the real program, so first-token checks work for these. The command can still be a compound (`a; b`), so a first-token allowlist alone is weak for compounds. Not observed on Linux (pending). Note the probe's `read_only` execute calls were never sent to the runner at all (see (b)).

(b) Which tool kinds does the adapter use for harmless tools? Observed on Windows:

| Tool title | kind sent |
|---|---|
| Find / Find `README.md` | `search` |
| Read File / Read `README.md` | `read` |
| ToolSearch | `other` |
| Write ... / Preparing file... | `edit` |
| Run git / Run command (execute) | `execute` |
| Approve Plan (permission only) | `switch_mode` |

`other` and `switch_mode` kinds occur, and `read_only` denies them. The permission update sent to the server shows `switch_mode` as `other`. The denied plan approval did not fail the run: the read_only run finished `cancelled` and nothing was written. The ad hoc probe also showed that in `read_only` (plan mode) the adapter ran `git status`, `ls` and `git log` without any permission request, so those were governed by Claude's own plan-mode rules, not by the runner's execute allowlist.

## Open items for the owner

1. Run the spike for codex on Windows and Linux, and for claude_code on Linux, and add the rows above.
2. `read_only` with Claude depends on plan mode: if the plan approval is ever allowed, the session leaves plan mode. The policy denies it today (`switch_mode` is not in the allowed set), which is what the spike observed.

## Fix found by the spike

`adapters.For` returned `npx.cmd` on Windows. Node installs without an `npx.cmd` (for example nvm-style installs that ship `npx.exe`) failed with `adapter_start_failed` although `megoocolab-runner doctor` passed. It now falls back to `npx` when `npx.cmd` is not on PATH.
