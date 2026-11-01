# Tool Hub: MCP servers and skills, kept once and pushed to your machines

Status: draft for the owner's approval · 2026-11-01

## Why

Each person on MegooColab uses MCP servers (for example, one that reads current library docs) and skills (for
example, UI-design guidance) that make their agents better. Today every one of them is set up by hand on every
machine, and again whenever a new agent goes on a new machine. Keys get copied around, and the setups drift apart.

The Tool Hub is a personal library inside MegooColab. You add each MCP server and skill once, with its keys. With
one push, the runner installs them at **user level** on any machine you own. You can also share tools with teams,
with specific people, or with everyone on the instance. Shared tools never carry your keys.

Success: adding an agent on a new machine takes one push to get every tool you rely on. A teammate can try a tool you
like without asking you how to set it up, and without ever seeing your key.

## Goals

- A personal library of MCP servers and skills, with secrets stored encrypted.
- Push that library (or part of it) to any of your machines. The runner installs it at user level for every agent
  program on that machine.
- Share tools with teams, with people, or with everyone, without their secrets. Whoever receives a tool supplies their
  own secrets.
- Show clearly when a machine doesn't match the library, and never change a machine without a push.
- Import tools you already set up by hand on a machine, when you choose to.
- Work on Windows, Linux and macOS, and for Claude Code and Codex today. Adding another agent program later (for
  example "OMP Agent") must be a runner-side addition only.
- Give admins control over sharing.

## Non-goals

- No outside marketplace or registry. The "Everyone" shelf is just what people on this MegooColab instance chose to
  share.
- No per-project or per-repository installs. User level only.
- No automatic push on edit. The owner chose a manual push with a visible "doesn't match" state.
- No pushing to machines you don't own. A runner token belongs to its user, so pushes only ever go to the pusher's
  own runners.
- No running or testing of MCP servers from the MegooColab server.

## Anti-goals (would make it a failure even if it works)

- A secret leaving MegooColab for anyone other than its owner's own runners, including through sharing, the "Everyone"
  shelf, admin views, logs, audit entries, API responses to other users, or the copy-to-library flow.
- The runner editing or deleting MCP entries or skills it did not install.
- Agents suddenly picking up the person's whole personal Claude Code setup (settings, hooks, CLAUDE.md). MegooColab's
  agents deliberately start without it (see "Agents must actually see the tools").
- Taking a shared tool that runs code on your machine without first seeing what it runs.

## Decided with the owner

- **Library, sharing, shelves.** The hub has three shelves: **Mine**, **Shared with me** and **Everyone**. Sharing
  sends the setup and files, never the secret values. Receivers see blank slots ("needs CONTEXT7_API_KEY") and fill
  in their own.
- **Machines are always the user's own.** Writing keys into user-level config files on them is acceptable.
- **Push goes through the runner, which translates per program.** The hub stores one neutral form. The runner has one
  translator per agent program (Claude Code and Codex now) that writes the tool in that program's own format. A new
  program means a new translator.
- **All three operating systems** must work.
- **Import is a button the user presses** on a machine. It is never automatic.
- **Changes wait for a push.** Machines that don't match the library are flagged, never silently updated.
- **Admins get a say** over sharing (see Admin).
- **Read-only runs.** Each MCP has a **"safe in read-only runs"** switch, off by default (owner chose this over
  allowing all hub MCPs, or allowing them only in build runs).
- **Admin removal** takes the tool off every shelf. Copies others took are marked "removed by an admin": they can't be
  pushed again, and machines that have one show "push to uninstall". Nothing changes on a machine until its owner
  pushes (owner chose this over a forced uninstall, or only stopping the sharing).
- **The mockup design was accepted.** It has four screens: the hub, Add MCP, a shared item, and the push panel per
  machine. Mockups are in `.superpowers/brainstorm/233-1793538929/content/tool-hub.html` and
  `tool-hub-installers.html`.

## What it is, piece by piece

### Tools

There are two kinds:

- **MCP server.** Its kind is either a *web address* (URL plus headers) or a *command* (program, arguments,
  environment variables). Every header and environment value has a **secret** switch.
  - **Keys inside an argument or the URL (my call).** A secret can be referenced there as a placeholder such as
    `${CONTEXT7_API_KEY}`, filled from a secret slot when the runner installs it. The setup that is shared only ever
    holds the placeholder. On save and on import, an argument or URL part that looks like a key is flagged, and you
    are offered the chance to turn it into a placeholder. A tool with a flagged value left in place cannot be shared
    until you either convert it or confirm it isn't a secret.
  - **"Safe in read-only runs" switch, off by default (owner's decision).** When it's on, the runner allows that
    MCP's tools in read-only runs (brainstorm, plan, review, answer). When it's off, they're allowed only in build
    runs.
    - Today `runner/internal/policy/policy.go` blocks every tool of kind "other" in read-only runs, except
      MegooColab's own `mcp__megoocolab`, so the switch has to reach the runner's policy.
    - The Add MCP screen explains the switch: turn it on only for tools that read and never change anything outside.
    - A copy someone takes starts with the switch off. They decide for themselves.
  - Secret values are stored encrypted with the existing `app/core/crypto.py`. They are only ever decrypted to go to
    the owner's own runner.
  - A command-type MCP can hold **a different command per operating system** when one setup doesn't fit all.
- **Skill.** A folder holding a `SKILL.md` and supporting files, in the SKILL.md folder format that Claude Code,
  Codex and others read.
  - You add it by uploading a folder or zip, or by importing it.
  - Files whose names look runnable (`.sh`, `.py`, `.ps1`, `.js`, …) are flagged as scripts, with the systems they
    probably need.

Each tool has a name, a description and a **version** that goes up whenever its setup or files change. Changing only
a secret does not create a new version, but it does make the owner's machines out of date.

### Sharing

You share a tool with any mix of: specific teams, specific people, and everyone. "Only me" is the default.

- **Adding a shared tool** to your library saves a **copy of that version**. The secret slots start empty. The copy
  remembers where it came from.
- **When the sharer publishes a new version**, your copy shows "Update available". Taking it is your choice, and your
  secrets are kept.
- **When the sharer stops sharing or deletes the tool**, copies already taken stay and keep working, marked "no
  longer shared".
- **Before adding**, the shared-item screen shows the full setup or every file, with a warning when the tool runs code
  on your machine.
- **Copies (my call).** A copy you took is read-only except for its secrets and its read-only switch. That keeps
  "Update available" simple: taking an update replaces the setup and files and keeps your secrets.
  - To change a copy, you press "Make it my own". That cuts its link to the source, so it stops getting updates and
    becomes a tool of yours.
  - Only your own tools can be shared, so a copy can be re-shared only after "Make it my own". That keeps the
    Everyone shelf free of plain duplicates, and keeps the "came from" chain one step long.

### Pushing (Settings › My agents)

The page gets one panel per machine. Each panel shows the machine's name, its operating system as reported by the
runner, and the agents on it.

**Which programs a push installs into (my call).** A push goes to the programs of the agents linked to that machine,
not to every program found on it. If a machine has Builder (Claude Code) and Reviewer (Codex), the push installs into
both. Codex installed on the same machine but never used with MegooColab is left alone.
- This list is known on the server even when the runner is offline. It also avoids guessing whether Claude Code is
  "installed": agents run through the `npx` adapter, so there may be no `claude` command at all.
- Linking an agent of a new program to a machine that already has tools makes that machine show "update ready" for
  the new program. The default-set rule ("install my default set on a new machine") only covers the machine's first
  push.

- **One line per tool**, with a tick and a state per program on that machine: installed, update ready, will install,
  changed on this machine, key missing, not supported by this program, or not available on this OS.
- **"Push N changes"** sends what is ticked. Unticking a tool and pushing removes it from that machine, in every
  program.
- **The runner reports back** per tool and per program what it actually did, and the panel shows that result.
- **Default set.** You can mark tools as your default set and switch on "install my default set on a new machine".
  When you add an agent on a machine that has never received a push, the default set is pushed there.
- **The badge.** The My agents link in the sidebar gets a small dot when any of your machines doesn't match.

A push only reaches a runner that is online. If it's offline, the push waits and is delivered when it reconnects, and
the panel says so.

### "Doesn't match"

The panel flags three cases:

- **Your library changed:** you edited a tool, changed a secret, or took an update. The state is "update ready".
- **The machine changed:** someone edited or deleted the runner-installed copy by hand. The runner checks its own
  entries when it connects and after each push, and reports "changed on this machine". Pushing puts your library's
  version back, after a confirmation that names what will be overwritten.
- **The source changed:** a tool you took from someone has a newer version. "Update available" shows on the hub. After
  you take it, the machine shows "update ready" as above.

### Import (button on a machine's panel)

- **What it reads.** The runner reads the user-level MCP entries and skills of every program it supports on that
  machine. It changes nothing.
- **Choosing.** You get a list and tick what to bring into your library. Values that look like keys or tokens are
  pre-marked secret, and you review each item before saving.
- **Duplicates.** The same MCP found in both Claude Code and Codex becomes one item.
- **After import,** the hand-made copy on that machine stays yours. The runner takes it over only on the first push of
  that tool to that machine, after a confirmation.

### Admin

- **A setting turns off the "Everyone" shelf.** Existing shares to everyone stop being visible. Their owners still
  have the tools.
- **Admins see every tool shared beyond "only me"** on a new admin page, and can stop the sharing of any of them, or
  remove one. This never shows secrets. Private tools are not listed.
- **What "remove" does (owner's decision).**
  - The tool disappears from every shelf, for everyone, and its owner sees it as "removed by an admin".
  - Every copy taken from it is marked "removed by an admin" as well. It can't be pushed to any machine, and it can't
    be "made my own".
  - Machines that have it show "push to uninstall" for that tool.
  - Nothing changes on a machine until its owner pushes.
- **Every share, unshare and admin removal** is written to the existing audit log.

## The runner side

- **A capability flag.** A new capability (for example `tools/1`) in the runner's `hello`. Machines whose runner
  lacks it show "Update the runner to use the Tool Hub", using the existing update arrow.
- **Messages.**
  - The server sends a push: the tools to install or remove, each in the neutral form, with the owner's secrets.
  - The runner answers with a report per tool and per program.
  - An import is a request plus a reply listing what was found.
  - The runner's report on which tools no longer match is sent when it connects.
- **Translators, one per program.**
  - **Claude Code:** MCP entries go in the user-level `mcpServers` of `~/.claude.json`. Skills go in
    `~/.claude/skills/<name>/`.
  - **Codex:** MCP entries go in `~/.codex/config.toml` under `[mcp_servers.<name>]`. Skills go in Codex's
    user-level skills folder.
  - A translator says what it can't take ("not supported"), and that state is shown rather than failing the whole
    push.
- **A record of what was installed (manifest).**
  - It lists what the runner installed, per program, with a fingerprint of each entry.
  - It is kept in the runner's own config folder.
  - It is how the runner knows what is its own to update or remove, and how it notices hand edits.
  - Entries not in the record are never touched.
  - If a hand-made entry has the same name as a tool being pushed, the push stops for that tool and asks: take it over,
    or skip.
- **Operating systems.**
  - Paths come from the machine's own home folder.
  - Known command fixes are applied by the translator, for example running `npx` through `cmd /c` on Windows.
  - A command with no setup for that system shows "not available on <OS>".
  - Files that hold secrets are made readable only by the user: owner-only permissions on Linux and macOS, and a
    user-only access rule on Windows.
  - Config files are written safely: read, change only our entries, write to a temporary file, then rename it into
    place. Formatting and unrelated entries are kept as far as the file format allows.

### Agents must actually see the tools

MegooColab starts Claude Code agents with `settingSources: []` (`runner/internal/adapters/adapters.go`, around
`SessionMeta`), so that a developer's personal settings don't leak into agent runs.

- **MCP servers.** By the Agent SDK's documentation, `~/.claude.json` is read regardless of that setting, so
  user-level MCP servers already reach agents.
- **Skills.** User-level skills do **not** reach agents.
- **The fix (my call).** The runner also hands the hub-installed skills to its Claude Code sessions directly (for
  example as a local plugin folder of only those skills) without turning on user settings. Agents get exactly the
  hub's skills, and the person's own Claude Code gets them too through `~/.claude/skills`.
- **Codex.** The builder must check the same for Codex through `codex-acp`: does it load user-level MCP servers and
  skills? If not, find the equivalent way to give its sessions the hub's tools.

## Constraints

- It follows the stack and patterns already in the repo:
  - the FastAPI backend with Alembic migrations;
  - the Next.js frontend using the existing UI components and the trail and Back patterns;
  - the Go runner using the existing WebSocket protocol and capability negotiation.
- Secrets use the existing Fernet helper. They are never returned by any API except the one that feeds the owner's
  own runner, and never logged.
- Size limits on skills (total size and number of files) are set by the builder at sensible values and enforced on
  both upload and import.
- Everything is testable with the fake agent and test server the runner already has, and with the e2e suite.

## Left to the builder

- Exact table layout, API shapes, message names and the capability string.
- How a skill's files are stored: in the database, or in the same place the app already keeps uploads.
- How a "looks like a key" value is detected on import.
- The size limits.
- How the Claude Code sessions are handed the hub's skills (the plugin-folder approach above, or something cleaner the
  SDK offers), and the Codex equivalent.
- Wording of states and empty screens, in the app's existing voice.
- Where "Tool Hub" sits in the sidebar (the mockup puts it under Memory).
- Checking against the Agent SDK and `codex-acp` that user-level `~/.claude.json` MCP entries really load with
  `settingSources: []`, and where Codex reads user-level skills.
- Writing `~/.claude.json` safely while a running Claude Code may also rewrite it, for example by retrying when the
  file changed between the read and the rename.
- What a queued push sends when the library changes before the runner reconnects. The sensible default is the
  library's state at delivery time, not at the moment of the push.
