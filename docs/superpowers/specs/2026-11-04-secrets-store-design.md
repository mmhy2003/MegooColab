# Secrets Store: credentials agents use without seeing them in prompts

Status: in review. Agreed in conversation:
- the owner's worry, in their words: "I just don't want the agents to see my passwords";
- they chose **option C**, both personal and project secrets;
- they answered "correct" to the played-back description, my guesses included;
- they approved that project secrets go to every member's agent on the project (see below).

Calls I made are marked **(my call)**. The mockup is
`.superpowers/brainstorm/768-1793778942/content/secrets-store.html` (git-ignored). This is the first of two features
asked for together; Agent Crons is designed separately.

## Why

Agents need credentials to do real work: an API key, a staging database password, a token for private packages.
Today the only way to give them one is to paste it into a task, a chat or a prompt. It then sits in MegooColab's
history and goes to the AI service.

The owner wants to store each credential once. Agents should get it as an environment variable on their machine and
use it by name (`$STAGING_DB_PASSWORD`) in commands, configuration and tools, without the value ever being written
into a prompt, a conversation or a log.

## What it can and cannot promise

The owner was told this, and the product says it where secrets are added.

**It promises:** a secret's value
- is never put in a prompt;
- is never stored in MegooColab outside its encrypted column;
- is never shown again after it is saved, to anyone;
- is blanked out of everything the runner sends back.

**It cannot promise** that an agent able to run commands never reads a value it was given, for example by
printing it to itself. The prompt tells agents never to print, log or commit secret values. Blanking makes anything
that slips through harmless in MegooColab.

**Project secrets reach members' machines (confirmed):**
- A project's secrets go to whichever agent works on the project, so any member whose agent is linked to the
  project receives them on their own machine, where they could read them. The owner accepted this.
- Likewise, someone using another person's agent on a project (as chats allow) directs an agent that holds the
  owner's personal secrets.
- The Secrets pages say so in one line.

## Goals

1. **A secret** has:
   - a **name**: an environment variable name, capital letters, digits and `_`, starting with a letter, at most 100
     characters;
   - a **description** of what it is, which the agent reads, at most 1,000 characters;
   - a **value**, at most 32 KB, stored encrypted.

   **Write-only value:** once saved, the value is never returned by any API or shown on any page. People can
   **replace** the value (a new one, entered blind), **edit** the name and description, or **delete** the secret.
2. **Two kinds** (the owner's option C):
   - **Personal secrets:** in **Settings › Secrets**. Each person manages only their own.
   - **Project secrets:** in **Project › Settings › Secrets**. The project's managers and admins manage them.
     **(my call)** Members see the list (names, descriptions, who changed what) but cannot add, edit or delete.

   A name is unique within one person's secrets, and within one project's.
3. **Who gets which.** When a run starts on an agent's machine, the runner is given:
   - the agent's **owner's** personal secrets, never those of the person who started the run (confirmed);
   - the **project's** secrets, when the run works on a project. For a run on a team's or the organisation's
     Knowledge Base draft, the owner's personal secrets only.
   - When a personal and a project secret share a name, the **project's wins** (confirmed), so a project behaves the
     same whichever agent works on it.
   - Every kind of run gets them (confirmed): workflow runs and reviewers, chats, Knowledge Base drafts, answers to
     other projects' questions. **(my call)** An answering run gets the *target* project's secrets, the project
     whose code it reads.
4. **Into the environment.**
   - **Delivery:** the runner sets the secrets as environment variables of the agent's process. They reach the
     commands and tools it starts, including MCP servers started from the agent's own configuration.
   - **Lifetime:** the values travel to the runner with the run's start, are held in memory only, and are never
     written to disk by the runner.
   - **Names that are refused:** a secret never replaces an environment variable the runner itself relies on
     (`PATH`, `HOME`, `USERPROFILE`, `SYSTEMROOT`, anything starting with `MEGOO`, and the variables of the agent
     program's own login and setup). **(my call)** The save refuses such names with a clear error.
5. **What the agent is told.** The run's prompt gains a section listing each secret it has, by name and
   description, saying:
   - they are set as environment variables;
   - use them by name (`$NAME` or `%NAME%`/`$env:NAME` on Windows) in commands and configuration;
   - never print, echo, log, commit or write their values to files.

   With no secrets, there is no section. The section's wording is part of each run role's editable methodology
   **(my call: one shared paragraph, not per role)**.

   Cron runs (Agent Crons) run commands, so they can use secrets in commands.

   **Read-only runs (my call):** brainstorm, plan, the reviewers, answering runs and Knowledge Base drafts run
   under the read-only command policy. That policy refuses any command that expands a variable (`$`, `%`,
   PowerShell `Env:`), and it stays as it is: loosening it is not worth the risk.
   - These runs still get the variables, so MCP servers in the agent's own configuration can use them.
   - Their prompt section says the secrets are available to the agent's configured tools, and that commands in
     this session cannot use them.
6. **Blanking.** The runner replaces every secret value it was given, wherever it appears, with `[NAME]`, in
   everything it sends to MegooColab:
   - run updates: messages, tool calls and results, plans, file changes;
   - the run's summary and errors;
   - steer results.

   This already happens for the run's own MCP token, and is extended to every secret. Values shorter than 4
   characters are not blanked, to avoid mangling text. **(my call)** The form warns that values that short can't be
   protected this way.

   **(my call)** The server blanks too. Agents also write straight to MegooColab's MCP server with their run token,
   bypassing the runner: designs, plans, reviews, decisions, test records, Knowledge Base text, memory, answers to
   other projects. So every MCP write from a run has the values of that run's secrets replaced with `[NAME]` on the
   server before anything is stored. For an answering run this keeps the target project's secrets out of the asking
   project.
7. **Changes are recorded.** The audit log records adding a secret, editing it, replacing its value, deleting it,
   and handing secrets to a run. It records names and who acted, never values. The list shows when each secret was
   last changed and by whom.
8. **Runner support.** A runner that cannot take secrets (an older version) still runs everything, without
   secrets. The agent's prompt then has no secrets section. Agents whose runner needs updating say so where secrets
   are managed and on the agent's page, as images and drafts do. A new runner capability (`secrets/1` suggested)
   says it can.

## Non-goals

- **Organisation-wide secrets** for every project. Admins can add the same secret to the projects that need it.
- **Reading a value back**, or importing and exporting secrets.
- **Secrets for things other than agent runs**, such as git webhooks or the Tool Hub's own MCP secrets, which
  stay as they are.
- **External vaults** (HashiCorp Vault, cloud secret managers).
- **Stopping a determined agent from reading a value it was given** (see "What it can and cannot promise").

## Anti-goals

- A value in a prompt, a task's or chat's activity, a run log in MegooColab, an API response, a page, or the audit
  log.
- A value written to disk on the agent's machine by the runner.
- A person's personal secrets reaching an agent they don't own.
- A secret silently replacing a variable the runner or the agent program needs.

## Constraints

- **Encryption:** values are encrypted with the server's existing `app.core.crypto` (Fernet keyed from
  `SECRET_KEY`), as Git tokens and Tool Hub secrets are. Rotating `SECRET_KEY` makes stored values unreadable. That
  is documented as for the other encrypted fields, not solved here.
- **Transport:** the runner's existing authenticated WebSocket carries the values with the run's start, as Tool Hub
  secrets already travel.
- **Platforms:** Windows, macOS and Linux runners alike.
- **Phones:** every new page and dialog fits 280 px wide, as the rest of MegooColab does.

## Testing

- **Backend:**
  - name validation and the refused names;
  - the value is never returned (list, get, edit, replace responses);
  - permissions: personal secrets are their owner's only; project secrets are managed by managers and admins, and
    members see the list only;
  - the set a run gets, for each run kind, with project-over-personal precedence and the owner's (not the
    requester's) personal secrets;
  - an older runner gets none, and the prompt has no section;
  - the audit log holds no value.
- **Runner:**
  - the agent's process gets the variables;
  - every kind of report back has values blanked;
  - short values are not blanked;
  - nothing is written to disk.
- **Frontend:**
  - both pages: the list, the add, edit and replace dialogs, the delete confirmation;
  - members' read-only view;
  - the runner-needs-updating notice.
- **e2e:** a project secret and a personal secret reach a fake agent's environment. The fake agent echoes one, and
  the run's activity shows `[NAME]` instead of the value.

## Left to the builder

- **Names:** of tables, routes, the capability and the run_start field.
- **Blanking:** how the runner does it efficiently for many secrets.
- **Variable names:** the exact list of agent programs' own variables that a secret may not replace.
