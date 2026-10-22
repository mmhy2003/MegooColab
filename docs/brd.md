# MegooColab — Business Requirements Document

| | |
|---|---|
| **Status** | Draft for review |
| **Date** | 2026-10-22 |
| **Owner** | Mohamed H. Youssef |
| **Product type** | Open-source, self-hosted web platform |

> **How to read this document.** Statements are the product owner's decisions unless marked **[Author's call]**, which are defaults chosen while writing this BRD that the owner has not explicitly confirmed. Items under §15 are deliberately left to the builder.

---

## 1. Summary

MegooColab is an open-source, self-hosted project-management platform where **humans and coding agents work as one team**. Managers and developers plan work on agile kanban boards; developers connect their coding agents (Claude Code, Codex) so MegooColab can **dispatch tasks to them and drive them** through a built-in, enforced engineering methodology (the [superpowers](https://github.com/obra/superpowers) workflow: brainstorm → design → plan → build → review). Agents of different developers can **ask each other questions** that require reading code only the other has. Everything people and agents write lands in a **Knowledge Base**, and a **collective memory** (modelled on [Honcho](https://github.com/plastic-labs/honcho), including its "dreaming" consolidation) continuously learns the organization's goals, products, projects and people so every agent starts with context.

## 2. Why

- Coding agents are now capable of doing much of a team's technical work, but today they live in individual terminals: managers can't see or assign their work, agents don't share what they learn, and quality depends on how each developer happens to prompt them.
- MegooColab makes agents first-class team members: assignable, visible on the board, held to the same engineering process, and contributing to (and drawing from) shared organizational knowledge.
- The owner's expectation: this changes how the team works, not just where tasks are tracked.

## 3. Goals, non-goals, anti-goals

### Goals
1. Humans and agents share one board; a task can be assigned to either.
2. MegooColab can **drive** a developer's coding agent end-to-end on an assigned task, with no copy-pasting by the developer.
3. Every agent-driven task follows the superpowers methodology, **enforced by the platform**, not by agent configuration.
4. Agents can get answers that require another project's codebase without a human relaying them.
5. Organizational knowledge accumulates automatically and is available to every agent and human with access.
6. Any organization can install and run it on their own servers.

### Non-goals (v1)
- Hosted SaaS / multi-organization tenancy. One install = one organization.
- Running agents on MegooColab's servers or in cloud sandboxes. Agents run on developers' laptops.
- Being a code host, CI system or IDE.
- LDAP / OIDC / SSO (planned for later; v1 must not block it).
- Supporting agents other than Claude Code and Codex in runner mode (the design must allow adding more ACP agents later).

### Anti-goals **[Author's call — owner skipped this topic]**
- Code leaving developers' machines through MegooColab. The platform sees tasks, progress, documents and answers, never the repository itself.
- An agent able to do more than its owner is allowed to do.
- Agent work moving forward without a human approving the design and the plan.
- Memory that can't be inspected or corrected by humans.

## 4. Deployment & distribution model

- **Self-hosted, single organization per install.** Distributed as Docker images with a Docker Compose file as the reference deployment.
- **Open source.** License to be confirmed by the owner; **[Author's call]** recommend Apache-2.0.
- **Scale target:** dozens of users and dozens of connected agents per install. A single server must be sufficient. No horizontal-scaling requirements in v1.
- **AI providers:** each organization supplies its own model/provider keys, configured in MegooColab and called via LiteLLM (used by the memory, dreaming, and any server-side AI features). Coding agents use their own subscriptions/keys on the developer's laptop.
- **Third-party content:** the superpowers methodology content is MIT-licensed and is embedded with attribution. Honcho is AGPL-3.0; MegooColab **re-implements its concepts natively and must not copy Honcho source code**.

## 5. Users & roles

### Personas
- **Admin:** installs and configures MegooColab, manages users, teams, settings, AI providers, and the methodology library.
- **Manager:** owns projects and sprints, assigns work, approves designs and plans, watches progress.
- **Developer (Member):** works on tasks directly and through their connected agents; approves designs/plans on their own tasks.
- **Viewer:** read-only stakeholder.
- **Agent:** a coding agent connected by a developer; acts on that developer's behalf.

### Roles & permissions **[Author's call on exact matrix]**

| Capability | Admin | Manager | Member | Viewer |
|---|:-:|:-:|:-:|:-:|
| Invite / create / deactivate users | ✓ | | | |
| Manage teams & membership | ✓ | ✓ (own teams) | | |
| Create projects, manage sprints & columns | ✓ | ✓ | | |
| Create / edit / assign tasks | ✓ | ✓ | ✓ (to humans or their own agents only, see AGT-5) | |
| Assign tasks to anyone's agent | ✓ | ✓ (projects they manage) | | |
| Answer agent questions, approve designs & plans | ✓ | ✓ | ✓ (tasks they own or are assigned) | |
| Connect agents & runners | ✓ | ✓ | ✓ | |
| Edit Knowledge Base | ✓ | ✓ | ✓ | |
| Correct / delete memory conclusions | ✓ | ✓ | own projects | |
| Edit methodology library, AI provider settings | ✓ | | | |
| Read everything in projects they belong to | ✓ | ✓ | ✓ | ✓ |

Project access follows team membership: a user (and their agents) can see a project if they belong to a team that the project belongs to. Admins see all.

## 6. Functional requirements

Requirement IDs are for traceability in the implementation plan.

### 6.1 Accounts & authentication

- **AUTH-1** MegooColab has its own authentication system. No self-sign-up.
- **AUTH-2** Admins add users either by **email invitation** (invitee sets their password via a time-limited link) or by **direct creation** (admin sets a temporary password; user must change it at first sign-in).
- **AUTH-3** Password reset via email. **[Author's call]** Optional TOTP two-factor authentication.
- **AUTH-4** Deactivating a user immediately revokes their sessions, their agents' tokens and their runners.
- **AUTH-5** The identity model must allow LDAP and OIDC providers to be added later without migrating existing accounts (e.g., external identity linked to a local user record).
- **AUTH-6** Personal access tokens, created by users from their profile, scoped and revocable, used by runners and MCP connections.
- **AUTH-7** SMTP settings are configured by the admin. Invitation and reset links can be copied by an admin when email isn't configured.

### 6.2 Teams

- **TEAM-1** Admins and managers create teams. A user can belong to many teams.
- **TEAM-2** A project belongs to one or more teams; membership grants access (see §5).
- **TEAM-3** Each team has a page listing its members, its agents (with online/offline status), and its projects.

### 6.3 Projects & tasks (agile)

- **PROJ-1** Hierarchy: Project → Epic → Task/Story → Subtask.
- **PROJ-2** Each project has a backlog and optional **sprints** (planning, active sprint board, burndown, velocity). Sprints can be turned off per project for continuous-flow teams.
- **PROJ-3** Kanban board with default columns **Backlog, To Do, In Progress, In Review, Done**. Managers can rename, add, remove and reorder columns per project.
- **PROJ-4** Every column is mapped to one workflow category, **before work / working / review / done**, so the workflow engine (§6.5) can move cards across custom columns.
- **PROJ-5** Task fields: title, description (Markdown), type, priority, story points, labels, due date, assignee (**a human or an agent**), reporter, watchers, attachments, linked tasks (blocks/blocked by/relates to), linked repository (§6.9).
- **PROJ-6** Task activity thread: comments by humans and agents, agent questions and answers, approvals, stage changes, live agent progress, all in one chronological thread.
- **PROJ-7** Filters and views: by assignee, agent, label, epic, sprint, and **"needs you"** (cards waiting on a human answer or approval).
- **PROJ-8** Real-time updates: board, task and agent status update live for everyone viewing.
- **PROJ-9** Each project has repository settings: which git repository/repositories it uses and the default branch.

### 6.4 Coding agents

#### 6.4.1 Agent registration
- **AGT-1** A developer registers one or more agents. Each agent has: a name (default "\<Owner\>'s Claude Code"), the agent program (**Claude Code** or **Codex** in v1), the projects it may work on, and for each project the local folder path of the repository on the developer's laptop.
- **AGT-2** An agent belongs to exactly one human owner and acts with **that owner's permissions**. Every action records both the agent and the owner.
- **AGT-3** Agent setting **"Answer other agents' questions": auto | manual** (see §6.6), chosen by the owner.
- **AGT-4** Agents appear as assignable members of their projects, with **online / busy / offline** status.
- **AGT-5** Who can assign tasks to an agent: its **owner**, plus **project managers and admins**. Other members cannot assign work to someone else's agent. (Assigning starts work on the owner's laptop and spends the owner's Claude/Codex subscription.)

#### 6.4.2 Runner mode (MegooColab drives the agent): primary mode
- **AGT-10** A **runner** is a small program the developer runs on their laptop. It authenticates with a personal access token and opens an **outbound** persistent connection to MegooColab (works behind NAT/firewalls; nothing listens on the laptop).
- **AGT-11** The runner is written in **Go** and shipped as a single self-contained binary for **Windows and Linux** (amd64 and arm64). **[Author's call]** macOS builds included because they're free to produce. Distributed via GitHub Releases plus a one-line install script for Linux and `winget`/`scoop` for Windows. It can run in the foreground or be installed as a background service.
- **AGT-12** When a task assigned to one of the developer's agents enters a working stage, MegooColab sends it to that developer's runner. The runner starts the agent through the **Agent Client Protocol (ACP)**, using the Claude Agent ACP adapter for Claude Code and the Codex ACP adapter for Codex, in the project's local folder.
- **AGT-13** The runner streams the agent's progress back to MegooColab, where it appears live on the task. It sends **metadata only**: the agent's own messages, plan updates, file names touched with line counts, command names, and test pass/fail results. It **strips file contents, diffs, and raw command/tool output** before sending.
- **AGT-14** The runner answers the agent's **permission requests** on MegooColab's behalf according to the current workflow stage (§6.5).
- **AGT-15** Build work happens in a **separate git worktree and branch per task** (e.g. `megoo/PAY-198-sync-orders`), never directly on the developer's checked-out branch.
- **AGT-16** Concurrency: **[Author's call]** one active task per agent by default; configurable by the owner.
- **AGT-17** Prerequisite check on startup: the runner verifies the agent program and adapter are available (Claude Agent ACP adapter requires **Node.js**) and reports clear setup instructions if not.
- **AGT-18** Cancel / pause: humans can stop an agent's current work from the task; the runner cancels the ACP session.
- **AGT-19** If a runner goes offline mid-task, the task shows "agent offline" and resumes from its last completed stage/step when the runner returns.

#### 6.4.3 Connect-only mode (agent reaches into MegooColab): secondary mode
- **AGT-30** MegooColab exposes a remote **MCP server** (Streamable HTTP, token auth). A developer adds it to Claude Code or Codex with a URL and token, with nothing to install.
- **AGT-31** MCP tools cover: list/read/create/update tasks, comment, move stages, read/write Knowledge Base, ask/search memory, ask another project's agents (§6.6), and fetch methodology instructions for a stage.
- **AGT-32** In connect-only mode MegooColab **guides but cannot enforce** the methodology (it doesn't control the session). The UI marks such tasks as "unenforced".
- **AGT-33** Runner-driven agents also receive this MCP server in their sessions so they can use the same tools.

### 6.5 Built-in superpowers workflow engine

The superpowers methodology is part of MegooColab itself. Nothing needs to be installed into Claude Code or Codex, and MegooColab is the authority on what stage a task is in.

- **WF-1** Agent-assigned tasks follow the stage track: **Brainstorm → Design → Plan → Build → Review → Done**.
- **WF-2** The stage track lives **inside** the agile board: when an agent-assigned task is in a "working" column, its card shows the stage track with the current stage highlighted. Finishing Build moves the card to the "review" column automatically, and passing Review (plus merge/PR, §6.9) moves it to "done".
- **WF-3** **Only MegooColab advances stages.** Agents can *request* advancement by submitting the stage's output; MegooColab checks exit criteria (below) and required approvals.
- **WF-4** For each stage, the runner starts the agent with **that stage's instructions only**, drawn from MegooColab's methodology library, plus the task, its thread, approved prior outputs, and relevant memory/KB context.
- **WF-5** Stage rules:

| Stage | What the agent does | Allowed actions (enforced via ACP permission requests) | Exit criteria |
|---|---|---|---|
| Brainstorm | Asks clarifying questions, one at a time, in the task thread | Read code, read KB/memory. **No code edits, no state-changing commands.** | Agent submits a design document |
| Design | Design document attached to task | Write the design doc only | **Human approval** |
| Plan | Writes an implementation plan of small steps | Write the plan doc only | **Human approval** |
| Build | Executes plan step by step, tests first, commits per step. **After each step, a fresh reviewer agent checks it** for spec compliance (matches design & plan) and code quality; findings go back for fixes and a scoped re-review | Edit files and run commands in the task's worktree | All plan steps done and each step's review passed; tests reported passing by runner |
| Review | **Automated final whole-branch review** by a reviewer agent; findings get one fix round and a scoped re-review | Read; fix findings in worktree | Final review clean. If the project has **"Require human code review"** turned on, also a human approval of the PR/MR in the git host |
| Done | Superpowers "finishing" step: re-verify tests, then **merge locally, push and open a PR/MR, or keep the branch**, per the project's default finishing option or the human's choice | Git merge / push / PR creation | Merge done, PR/MR opened, or branch kept (§6.9) |

- **WF-6** Questions and approvals can be handled by **either the owner of the assigned agent or a manager of the project**. Whoever acts first wins; the thread records who it was. Cards waiting on a human show **"needs you"**, and the relevant people are notified.
- **WF-6a** Code review follows the superpowers method: it is **automatic** (per-step reviews during Build plus a final whole-branch review) and needs no human. Each project has a setting **"Require human code review before Done"**, **off by default**; when on, the card waits in the review column until a person approves the PR/MR in the git host. All review findings and their resolution are shown on the task.
- **WF-6b** Each project sets a **default finishing option**: merge locally, push and open a PR/MR (default **[Author's call]**), or keep the branch. Humans can override it per task.
- **WF-6c Agent questions in the task thread.** Whenever an agent needs human input (most often during Brainstorm, one question at a time), the question appears in the task's thread:
  - Agents ask through a MegooColab MCP tool (`ask_human`-style) that takes the question plus optional **choices** (each with a short description and a recommended flag). The thread renders choices as clickable buttons, always with a free-text "Other" reply; plain-text questions are also supported.
  - After asking, the agent ends its turn. The card shows **"needs you"** and the owner/managers are notified (WF-6).
  - The human's reply (a click or text) is sent back to the runner, which continues **the same agent session** through ACP, so the agent keeps its conversation context. If the laptop restarted in between, the runner reloads the saved session (the Claude Agent ACP adapter supports loading sessions from disk); if that fails, it starts a new session seeded with the full task thread.
  - The whole Q&A stays in the thread as a record and is fed to memory. **[Author's call on mechanics]**
- **WF-6d Visual mockups in the thread (v1).** When seeing beats reading (screen layouts, visual styles, diagrams, side-by-side options), the agent can attach an **HTML mockup** to its question, as the superpowers brainstorming "visual companion" does:
  - Posted through an MCP tool together with the question; rendered inline in the thread as a preview, with an option to open it full-screen.
  - Mockups can mark clickable choices; clicking one records the human's selection as the reply (same flow as WF-6c), and free-text feedback is still possible.
  - Rendered in a **sandboxed frame** (no access to MegooColab's session, cookies, or API; served from an isolated origin with a strict content-security policy; external network limited to an allowlist such as web fonts). **[Author's call on the security model]**
  - Iterations are kept as versions in the thread; the chosen mockup is attached to the design document and copied to the Knowledge Base.
  - Size limit per mockup **[Author's call: 2 MB]**.
- **WF-7** Approved plans become **subtasks / a checklist** on the card; Build shows "*n* of *m* steps done".
- **WF-8** Rejection: a human can send a design or plan back with comments; the agent revises in the same stage.
- **WF-9** **MegooColab is the home of design documents and plans.** They are stored in MegooColab, attached to the task and filed in the project's Knowledge Base, with version history and approvals, not in the repository. Specifically:
  - Agents write and read them through MCP tools; in Brainstorm, Design and Plan stages the agent never writes to the repo.
  - When Build starts, the runner places a **read-only copy** of the approved design and plan in the task's worktree under a git-ignored folder (e.g. `.megoocolab/`) so the agent can read them as files.
  - Plan progress is tracked in MegooColab (plan steps → subtasks, WF-7), not by editing checkboxes in a file.
  - Per-project setting **"Also commit design and plan to the repo"** (off by default): when on, they're committed into the task branch at the finishing step under `docs/superpowers/specs/` and `docs/superpowers/plans/`.
- **WF-10** **Methodology library:** ships with the superpowers methods built in. In v1, admins can **edit the instruction text of the six fixed stages**; the stages themselves, their allowed actions, exit criteria and approval rules are fixed. Every change is versioned and each task records which version it ran with. Custom stage tracks are a post-v1 feature, so the engine should not preclude them.
- **WF-11** Humans may opt in to the stage track on their own tasks as a non-enforced checklist.

### 6.6 Agent-to-agent questions

- **A2A-1** An agent (or human) can ask a question addressed to **a project** (not a person), e.g. "What payload does the `/orders/sync` webhook send and how are retries signed?", with optional context (task, errors, what was tried).
- **A2A-2** MegooColab routes it to an **online runner of a member of that project** whose agent has that project's repository locally. If several qualify, any may take it.
- **A2A-3** The receiving runner starts a short **read-only** answering session: read code only, no edits, no state-changing commands. The answer cites files and lines read.
- **A2A-4** If the answering agent's owner set **manual** mode, the drafted answer waits for the owner's approval (with edit) before being sent; in **auto** mode it's sent immediately.
- **A2A-5** If no suitable runner is online, the question is **queued**; the asking task is marked "waiting on \<project\>" and the asking agent may move on to other work. Human members of the target project may answer directly.
- **A2A-6** Every answered question is stored in the target project's Knowledge Base (Q&A section) and fed to memory, so repeat questions are answered without reading code again. Before routing, MegooColab first checks KB/memory for an existing answer and offers it.
- **A2A-7** Incoming questions are **untrusted input**: answering sessions must never reveal secrets, credentials or environment values, and run under the read-only permission policy. All questions and answers are visible to the target project's members.

### 6.7 Knowledge Base

- **KB-1** Markdown documents organized by **organization**, **team** and **project** spaces, with folders.
- **KB-2** Humans edit in the web UI; agents read/write via MCP. Every revision is versioned with author (human or agent + owner) and diff view.
- **KB-3** Full-text and semantic search.
- **KB-4** Automatic contributions: approved designs and plans (WF-9), agent-to-agent Q&A (A2A-6). **[Author's call]** Also review summaries.
- **KB-5** Permissions follow the space: org space readable by all, team/project spaces by members.
- **KB-6** Documents can link to tasks and to other documents.

### 6.8 Collective memory (native, Honcho-style)

Re-implements Honcho's concepts inside MegooColab's own codebase and database.

- **MEM-1 Entities ("peers"):** people, agents, teams, projects, products, and the organization itself.
- **MEM-2 Inputs:** task threads, agent work-session metadata streamed by runners (AGT-13, no code contents), agent-to-agent Q&A, review findings, Knowledge Base documents.
- **MEM-3 Continuous learning:** a background worker processes new inputs and records short **conclusions** about entities (e.g. "Project Y's webhooks retry 3 times with HMAC signatures"), each linked to its **source** (message, document, session).
- **MEM-4 Dreaming:** a scheduled (default nightly) and on-demand consolidation run that:
  - replaces outdated conclusions and resolves contradictions,
  - deduces conclusions that logically follow from existing ones,
  - induces patterns across multiple conclusions (requires ≥2 supporting conclusions, with confidence),
  - links conclusions to their premises (a reasoning chain viewable by humans),
  - refreshes a short **summary card** per entity (project, team, person, agent, organization).
- **MEM-5 Ask the memory:** humans and agents ask natural-language questions ("What is Project Y trying to achieve this quarter?") and get a reasoned answer citing the conclusions it used. Exposed in the UI and via MCP.
- **MEM-6 Context injection:** when the runner starts an agent on a stage, MegooColab includes the relevant entity cards and conclusions for that task and project.
- **MEM-7 Access control:** memory is scoped like everything else. An agent or human can only recall conclusions derived from projects/spaces they can access. Organization-level conclusions are visible to all.
- **MEM-8 Human control:** browse conclusions per entity, see sources and reasoning chain, correct, delete, or pin conclusions. Deleted/corrected items are not re-derived from the same source.
- **MEM-9** Hybrid retrieval: PostgreSQL full-text search + pgvector similarity.
- **MEM-10** All LLM and embedding calls go through LiteLLM with admin-configurable models per job (conclusion extraction, dreaming, answering, embeddings) and per-job cost visibility. **[Author's call]**

### 6.9 Git integration

- **GIT-1** Supported providers: **GitHub, GitLab (cloud and self-hosted), Gitea/Forgejo** **[Author's call on the self-hosted set]**, plus **plain git** (no provider API).
- **GIT-2** Pushing branches and opening PRs/MRs happens **on the developer's laptop by the agent/runner, using the developer's own git credentials**. MegooColab does not hold write credentials to repositories. When humans review code (only if the project requires it, WF-6a), they do so in the git host's PR/MR; MegooColab links to it and never renders the diff itself. For plain git, the branch is pushed and reviewers check it out. **[Author's call]**
- **GIT-3** MegooColab tracks PR/MR status (open, merged, closed, checks) via the provider API using a read-only token configured per project, and/or provider webhooks, to drive the Done stage.
- **GIT-4** For plain git without an API, a human marks the task as merged.
- **GIT-5** Tasks show linked branch and PR/MR.

### 6.10 Notifications **[Author's call]**

- **NOT-1** In-app notification center and email for: "needs you" (question/approval), task assigned, mentions, agent offline mid-task, questions to your project waiting for an answer.
- **NOT-2** Per-user notification preferences.

### 6.11 Administration & audit

- **ADM-1** Admin settings: organization profile, SMTP, AI providers/models (LiteLLM), dreaming schedule, methodology library, git provider connections, defaults for new projects.
- **ADM-2** Audit log of security-relevant and agent actions: sign-ins, token creation/revocation, permission changes, agent sessions started/stopped, stage approvals, memory deletions.
- **ADM-3** Agent overview: all agents, owners, status, current task, recent activity.

## 7. Non-functional requirements

- **NFR-1 Security:** all traffic over TLS in production; tokens hashed at rest; secrets (provider keys, git tokens) encrypted at rest; least-privilege token scopes.
- **NFR-2 Code locality:** source code is never uploaded to MegooColab by design. The runner strips file contents, diffs and raw output (AGT-13); code review happens in the git host (GIT-2). Only text that agents/humans explicitly post (messages, docs, answers with snippets) is stored.
- **NFR-3 Prompt-injection hygiene:** all content coming from other agents, tasks or documents is treated as untrusted data when assembled into agent context; answering sessions are read-only (A2A-7).
- **NFR-4 Real-time:** board/task/agent updates visible to viewers within ~2 seconds.
- **NFR-5 Resilience:** runner reconnects automatically; tasks resume from last completed stage/step; background jobs are retried and idempotent.
- **NFR-6 Install:** a fresh install via Docker Compose plus first-admin setup takes under 15 minutes for a competent ops person. Database migrations via Alembic run automatically on upgrade.
- **NFR-7 Cross-platform runner:** first-class Windows and Linux support (paths, process spawning, services).
- **NFR-8 Accessibility:** both themes meet WCAG AA contrast for text; glow effects are decorative and never the only state indicator; respects `prefers-reduced-motion`.
- **NFR-9 Observability:** structured logs; health endpoints; per-job LLM usage/cost.
- **NFR-10 API-first:** every UI capability is available through the documented REST API (OpenAPI), which also generates the runner's Go types.

## 8. Architecture & tech stack

### Decided by owner
- **Frontend:** Next.js, Tailwind CSS, Lucide icons.
- **Backend:** FastAPI, Alembic, PostgreSQL, LiteLLM.
- **Runner:** Go, using the ACP Go SDK (`coder/acp-go-sdk`).
- **Agent protocols:** ACP for MegooColab → agent (runner mode); MCP for agent → MegooColab (both modes).

### [Author's call] Supporting components
- **pgvector** extension in PostgreSQL for embeddings.
- **Background worker** process (same codebase as the API) for memory learning, dreaming, notifications, git status sync, and question routing timeouts. Queue implementation left to builder (§15).
- **WebSockets** from the backend for live UI updates and for the runner's persistent connection.
- **MCP server** hosted inside the FastAPI app (Streamable HTTP).

### Component view

```
 Browser (Next.js) ──HTTPS/WebSocket──┐
                                      ▼
                         ┌──────────────────────────┐
 Claude Code / Codex ───▶│  MegooColab API (FastAPI) │◀── Git provider webhooks / API
   (connect-only, MCP)   │  REST · MCP · WebSocket   │
                         └────────┬─────────────────┘
                                  │
             ┌────────────────────┼──────────────────────┐
             ▼                    ▼                      ▼
     PostgreSQL + pgvector   Background worker        LiteLLM → org's model providers
                             (memory, dreaming,
                              notifications, git sync)
                                  ▲
 Developer laptop                 │ outbound WebSocket (token)
 ┌───────────────────────────────┴──────────┐
 │ megoocolab-runner (Go)                    │
 │   └─ ACP ─▶ Claude Agent ACP adapter ─▶ Claude Code
 │   └─ ACP ─▶ Codex ACP adapter        ─▶ Codex
 │   local repo + per-task git worktrees     │
 └───────────────────────────────────────────┘
```

## 9. Visual design

Direction chosen by owner: **"Neon Grid"** (synthwave cyberpunk), in both dark and light themes, with a theme toggle that defaults to the system preference.

| Token | Dark | Light |
|---|---|---|
| Background | `#0D0221` with faint cyan grid | `#F6F3FF` with faint violet grid |
| Surface / card | `#170838` | `#FFFFFF` |
| Border | `#2E1A66` | `#D6CCF5` |
| Text / muted | `#E9E4FF` / `#8F84C0` | `#1A0B3D` / `#6B5F99` |
| Primary accent (cyan) | `#05D9E8` + glow | `#0090A8`, no glow |
| Secondary accent (hot pink) | `#FF2A6D` + glow | `#D4004F` |
| Success / online (neon green) | `#7CFF6B` | `#1F8F2C` |

- **Fonts:** Orbitron for headings/brand, Share Tech Mono for UI text and IDs. **[Author's call]** The builder may substitute a more readable body font for long-form Knowledge Base content if Share Tech Mono hurts readability.
- **Signature elements:** neon glow on focus/active states and on the agent currently working; stage track bar on agent cards; "NEEDS YOU" pink badge; online-agents chip in the header.
- **Icons:** Lucide.
- Light theme keeps the same hues darkened for contrast and replaces glow with crisp shadows.
- Reference mockup produced during brainstorming: `.superpowers/brainstorm/*/content/visual-style.html` (option A).

## 10. Feasibility notes (checked against current documentation, Oct 2026)

| Topic | Finding | Implication |
|---|---|---|
| ACP transport | Standard ACP runs the agent as a **local subprocess over stdio**; the client launches it. | Driving agents requires something on the laptop → the runner. |
| Remote ACP | HTTP/WebSocket transport for ACP exists only as an **RFD (proposal)**; the agent would still run on the laptop. | Not a substitute for the runner; revisit later. |
| Claude Code via ACP | Official **Claude Agent ACP adapter** (`agentclientprotocol/claude-agent-acp`), a Node package. Supports permission requests to the client when a tool isn't auto-approved. | Runner requires Node.js on the laptop. See risk R1 about user settings that auto-approve tools. |
| Codex via ACP | Official **Codex ACP adapter** (`agentclientprotocol/codex-acp`). | Supported in v1. |
| Go ACP SDK | `coder/acp-go-sdk` provides client-side ACP in Go. Official SDKs exist for TS, Python, Rust, Kotlin. | Go runner is viable; Go SDK is community-maintained by Coder (track updates). |
| Claude Code "channels" | MCP servers can push events into a running Claude Code session, but it's a **research preview**, allowlisted, Claude-only, stdio-only. | Not used in v1; possible later enhancement for connect-only mode. |
| Honcho | FastAPI + Postgres/pgvector + background "deriver" + "dreamer" (deduction & induction specialists, reasoning trees, peer cards). **AGPL-3.0.** | Concepts map cleanly onto our stack; re-implement natively, copy no code. |
| superpowers | MIT-licensed skills defining brainstorming → plans → TDD build → review → finish. | Embed content with attribution in the methodology library. |

## 11. Release scope

**Everything in §6 ships in the first release (v1); there is no feature split.** The builder should still sequence work into internal milestones that are individually demoable, e.g.:

1. Foundation: auth, users, teams, projects, tasks, boards, sprints, real-time, theming.
2. Agents: registration, tokens, MCP server (connect-only mode), runner skeleton with ACP for both agents.
3. Workflow engine: stages, permission enforcement, approvals, worktrees, plan→subtasks.
4. Knowledge Base.
5. Memory: learning, ask-the-memory, context injection, then dreaming.
6. Agent-to-agent questions.
7. Git integration, notifications, admin, audit, installer polish.

**Team and timeline:** not yet set by the owner. The implementation plan should state its staffing assumption, show which milestones can run in parallel (notably the Go runner alongside the web platform), and flag if a target date and the full v1 scope don't fit.

## 12. Success criteria **[Author's call]**

- A developer can go from receiving an invitation to watching their agent work on an assigned task in **under 30 minutes**.
- A task can travel **To Do → Done** with the agent doing all technical work, including code review, and humans only answering questions and approving the design and plan.
- An agent's question about another project's code gets an answer without a human relaying it, and the same question asked later is answered from KB/memory.
- After a few weeks of use, asking the memory about a project's goals returns an accurate, sourced answer that the team agrees with.
- A new organization can install and configure MegooColab from the docs alone.

## 13. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | **Enforcement gaps:** a developer's own Claude Code/Codex settings may auto-approve tools, so the runner never sees a permission request. | Runner launches agents with an isolated config/profile and explicit permission mode (e.g. ask/plan/read-only sandbox per stage); verify early with a spike on both adapters, on Windows and Linux; stage outputs are additionally validated server-side (e.g. no commits before Build). **Agreed fallback:** if an adapter/OS combination can't be reliably locked down, it still ships in runner mode, its tasks are labelled **"partially enforced"**, and server-side checks of each stage's output are relied on. The adapter is not dropped. |
| R2 | ACP and adapters are young and change quickly. | Pin adapter versions per runner release; isolate ACP handling in one runner module; contract tests against both adapters. |
| R3 | Runner offline at key moments (laptop closed). | Clear status, queueing, resume-from-step, notifications. |
| R4 | Memory quality: wrong or stale conclusions mislead agents. | Sources and reasoning chain visible; human correct/delete; dreaming resolves contradictions; confidence on induced patterns. |
| R5 | LLM cost of continuous learning and dreaming. | Per-job model selection, batching, cost visibility, adjustable schedule. |
| R6 | Prompt injection via cross-agent questions or documents. | NFR-3, read-only answering sessions, secret redaction, visible audit. |
| R7 | Large v1 scope (no feature split). | Milestone sequencing (§11) with internal demos. |

## 14. Decisions log

**Owner decisions:** product purpose; target users (technical teams and managers); all seven feature areas in v1; tech stack; runner mode preferred, driven by MegooColab; runner runs on developer laptops; runner in Go for easy Windows/Linux use; superpowers built into the platform and enforced, not installed in agents; approvals by owning developer **or** manager; agent-to-agent auto/manual answering set by agent owner; native Honcho-style memory **with dreaming**; agile + superpowers combined; own auth with email invites and direct creation, LDAP/OIDC later; any organization can use it, self-hosted, one org per install; open source; GitHub, GitLab and self-hosted git; scale of dozens; Neon Grid visual style; runner sends metadata only (no code contents); only the agent's owner, project managers and admins can assign work to an agent; v1 methodology customization limited to editing stage instructions; "partially enforced" fallback if an adapter can't be locked down; code review is automatic as in superpowers, with human code review an optional per-project setting, off by default; agent questions appear in the task thread with clickable options; visual mockups in the task thread are in v1; designs and plans live in MegooColab (task + KB), with an optional per-project setting to also commit them to the repo.

**[Author's call] items** are marked inline throughout; main ones: role matrix, TOTP, Apache-2.0 recommendation, macOS runner builds, one task per agent default, git pushes from the laptop with the developer's credentials, Gitea/Forgejo support, notifications set, "push and open PR/MR" as the default finishing option, human code review (when enabled) done in the git host, success criteria, anti-goals.

## 15. Left to the builder

- Database schema, API design, and module structure.
- Job queue implementation for the background worker (PostgreSQL-backed queue preferred to avoid extra services; Redis acceptable).
- Real-time transport details (WebSocket vs SSE for the browser).
- Exact MCP tool names and schemas.
- Runner packaging details and service installation per OS.
- Embedding model and default LLM choices (configurable anyway).
- Exact prompts used for memory extraction, dreaming and answering.
- Rich-text vs. pure Markdown editor for the KB.

## 16. Glossary

- **ACP (Agent Client Protocol):** JSON-RPC protocol a client uses to start and drive a coding agent (prompts, streamed updates, permission requests).
- **MCP (Model Context Protocol):** protocol an agent uses to call external tools and data (here, MegooColab's tools).
- **Runner:** MegooColab's program on a developer's laptop that receives tasks and drives agents via ACP.
- **Stage track:** the superpowers stages shown on an agent-assigned card.
- **Conclusion:** a short fact the memory has derived about an entity, linked to its source.
- **Dreaming:** scheduled consolidation of conclusions (dedupe, update, deduce, induce, refresh cards).
- **Entity card:** a short, regularly refreshed summary of a project, team, person, agent or the organization.
