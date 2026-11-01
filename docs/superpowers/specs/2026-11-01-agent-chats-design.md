# Agent chats — design

Approved in conversation with the owner on 2026-11-01. Mockup: `.superpowers/brainstorm/2839-1793520974/content/chats.html`
(layout option C chosen).

## Why

Everything an agent does in MegooColab today starts from a task: a card on the board, assigned to an agent, moved into
work. For quick fixes and maintenance ("the login page throws on an empty email, fix it", "bump this dependency") that
is ceremony before the work. The owner wants what an open Claude Code or Codex session gives: pick a project, start
talking to an agent, get the work done — while keeping MegooColab's discipline.

## What a chat is

A **chat** is a conversation with an agent about one project. The project is required; the agent can be chosen or left
to MegooColab to pick a free one.

A chat **follows the same flow a task does today** (owner's choice, "like how the task does today"): the agent talks
with the person to understand the request (its questions with answer buttons), writes a design the person approves,
writes a plan the person approves, builds it step by step with reviews, and finishes the way the project is set to
(merge or pull request). The stops for approval are the same as a task's.

What's different from a task is only how it starts and where it lives: no card, column, sprint or assignee to set up
first. The person types what they want, and the session begins.

**When a round of work finishes** — merged, or a pull request opened (approved or merged, when the project requires a
person's code review) — or the person presses **End chat**, MegooColab asks **"Add this to the board?"** (owner's
decision). Yes creates a task with the details; No doesn't.

**A chat can go round again** (owner's request, my recommended shape): after a round finishes, the person can keep
typing in the same chat to ask for another feature or fix. That starts **round 2**: the whole flow again — talk,
design, plan, build, finish — in the same conversation, with everything said before still in view and in the agent's
context. See "Rounds" below.

## Goals

1. Start a chat from a project in a couple of clicks: project (required), agent (optional), first message.
2. A conversation view where the person's messages reach the agent as they type them, even while it works, and the
   agent's questions, design, plan, progress and finish appear inline with the same actions a task offers.
3. The same workflow guarantees as a task: approvals, reviews, enforcement, finishing, records, history.
4. Every chat is findable afterwards with its status; finished ones stay readable.
5. On ending, an optional task on the board that records what was done.

## Non-goals

- A general assistant with no project, or across several projects.
- Talking to an agent without its runner (chats run on the person's machines like tasks do).
- A lighter flow that skips design or plan approval (the owner chose the task's flow). The agent's methodology may
  still keep a trivial request's design and plan short.
- Sharing a chat with other people as participants. Others who may see it can read it (see Visibility).

## Anti-goals

- A chat leaving work behind silently: a branch or uncommitted change nobody can find.
- Two chats (or a chat and a task) on one project stepping on each other's files.
- Chats cluttering the board, backlog, sprints or reports when the person said "No" at the end.
- A second workflow engine that drifts from the task one.

## Where chats live (owner's choice: option C)

- **A "Chats" page in the sidebar** (between Projects and Questions), listing every chat the viewer can see across
  projects, with a project filter ("All projects ▾"). Unread/waiting count badge on the menu item, like Questions.
- **A "Chats" tab in each project** (next to Board and Settings): the same view filtered to that project, with
  **New chat** preset to it.
- Both are the same component: a list on the left, the selected chat on the right. On a phone, the list and the chat are
  separate screens.

### The chat list

Each row: the chat's title (the agent's short summary of the request; the first message's start until it has one),
the project key (on the sidebar page), and its state:
"talking", "waiting: answer the agent's question", "waiting: approve the design/plan", "building step N of M",
"in review", "finished · PR #42" / "finished · merged", "ended, no changes", "offline — starts when <owner>'s runner
connects". Ordered by last activity; ones waiting on the viewer first.

### New chat

A dialog: **Project** (required; preset on a project's tab), **Agent** (any free agent the person may use on that
project, or a specific one — the same choice and rules as assigning an agent to a task), and the **first message**.
Send creates the chat and starts the session.

### The chat view (mockup section 2)

- Header: title, project chip, agent chip (name · program), the progress line Talk → Design → Plan → Build → Finish
  with the current stop highlighted, and **End chat**.
- Conversation: the person's messages; compact activity lines for what the agent read/searched/ran (as Activity shows
  them today); the agent's messages; its questions with answer buttons; the design and plan as cards with
  **Approve** / **Ask for changes**; build progress (steps, reviews, decisions, test runs); the finish (PR link or
  "merged").
- Composer at the bottom, always available while the chat is open. **What a message does depends on what the chat
  is waiting for** (owner's decision, as recommended):
  - the agent asked a question → the message is the person's answer (a free-text answer, as on the question card);
  - a design or plan waits for approval → the message is **Ask for changes** with that text; the agent revises and
    resubmits; **Approve** stays on the card;
  - the agent is working → a "tell the agent" message, read straight away in its running session (plan 20);
  - nothing waits and nothing runs (e.g. after an escalation was decided) → the message starts the agent again with
    that text;
  - the round has finished → the message starts the next round (see Rounds).
  The line under the composer says which of these will happen before the person sends.

### Ending a chat (mockup section 3)

The dialog "Add this to the board?" with **Title** and **Description** (filled in by MegooColab from the chat:
the request, what was decided, what changed, the PR or merge, a link back to the chat) and **Column** (Done when the
work finished; the project's first column otherwise), both editable. **Create task** / **No, just end it**.

**End chat** while the agent is working stops its run first (with a confirmation). Whatever the agent committed stays
on its branch; the dialog says so ("The branch megoo/… keeps what was done so far").

## Rounds

- After a round finishes, the chat doesn't close: the composer says "Starts a new round: the agent talks it through,
  then design, plan, build and finish again." Sending starts round N+1.
- The conversation is one continuous thread; a divider marks each round ("Round 2 · Add retries to the payment
  API"), and the header's progress line shows the current round. The chat list shows the latest round's state.
- The new round's agent gets the earlier rounds as context: their requests, the approved designs and plans, what was
  delivered (PR/merge), and every instruction the person gave (kept in mind, as with tasks).
- **Where round 2 starts from:** the default branch when round 1 was merged; **round 1's branch** when its pull
  request is still open, so the changes stack and don't conflict. The person can change it (the same "Branch from"
  choice a task has), shown in the round's divider.
- **The board question is asked per round**, since each round is its own piece of work: "Add this to the board?"
  after each finished round, and for the current round on **End chat**.
- **End chat** ends the chat for good (read-only). A new idea later starts a new chat, or the person simply keeps the
  chat open and starts another round.
- My recommendation on when to start a new chat instead: when the new request is about something unrelated, a new chat
  keeps the list readable and the agent's context focused. The chat doesn't force this; the agent's first reply in a
  new round may suggest it when the request looks unrelated.

## Knowledge Base and memory (owner's request)

- A chat's approved design and plan, and its final review, are filed in the Knowledge Base exactly as a task's are
  (WF-9), whether or not the chat is added to the board.
- Memory learns from a chat's conversation, decisions and runs as it does from a task's, so later chats and tasks
  benefit.
- In both, the "from"/source link opens the chat; it opens only for people who can see the chat (others see the entry as
  they would a task's, under the same project rules).

## Dashboard (owner's choice: option B; mockup `.superpowers/brainstorm/2839-1793520974/content/dashboard.html`)

- A new KPI tile **"Open chats"**: the count of open chats in scope, with "N waiting on you" underneath.
- **Needs you** lists chats waiting on the viewer, tagged "chat", opening the chat.
- **Running now** shows a chat's agent run, tagged "chat", with its stage/step.
- A new **Chats** card: open chats in scope, most recent activity first, each with what it's doing ("waiting: plan",
  "building 2/3", "in review · PR #42", "finished"), and links **New chat** and **All chats**.
- **"Tasks finished · last 14 days"** gets a third colour: chats (a round that finished), next to tasks by agents and by
  people; the card's title becomes "Finished · last 14 days".
- The Mine / Team / All switch filters chats like everything else (Mine: chats I started or whose agent I own).

## How it works underneath (my recommendations, approved with the designs)

- **One engine.** A chat runs on the existing task workflow engine — the same runs, approvals, reviews, enforcement,
  records, branch and finishing — so nothing is built twice and the two can't drift.
- **Own branch and worktree.** Each chat gets its own branch and worktree like a task, so two chats on one project
  never collide.
- **Messages.** The person's messages in a chat are "tell the agent" messages (plan 20): instructions, delivered into
  the running turn or at the next run, kept in mind by every later run.
- **Visibility.** A chat is visible to the person who started it, the agent's owner, the project's managers and
  admins. They can read it; only those who may direct the agent (WF-6) can send messages or approve.

## The builder's calls I made (check while reading)

- **A chat holds rounds; each round is a hidden task under the hood.** The workflow engine is keyed on a task (runs,
  documents, questions, records, events all hang off `task_id`). A chat is a small record of its own (project, starter,
  agent, title, state) with one or more rounds, each a `Task` row marked as a chat round and kept out of the board,
  backlog, sprints, search and reports. "Create task" at the end of a round turns that round's row into an ordinary
  task (with the edited title, description and column), so its history — conversation, design, plan, reviews, PR —
  comes with it. The chat view shows all its rounds' activity as one thread.
- **Rounds take the project's next task number,** so a round that becomes a task keeps its key. Board numbering has a
  gap for each round that stays a chat. (Numbering only on conversion would change keys that branch names and links
  already use.)
- **Code review.** When the project requires a person's code review, a round shows "in review" until the pull request
  is approved or merged, then finishes and asks about the board. **End chat** while in review ends the chat but
  MegooColab keeps tracking the pull request; a task created then goes into the project's review column, not Done.
- **Ended chats are read-only.** A task created from a round ended early keeps its paused workflow, so moving it into a
  working column carries on where the chat stopped.
- **Plan steps aren't subtasks on the board for chats.** The steps live in the plan inside the chat; if a round becomes
  a task, its step subtasks are created then, in the state each step reached. So a round uses one task number.
- **Notifications.** The person who started the chat, and the agent's owner if someone else, get the usual
  notifications (agent question, approval needed, finished, escalation), linking to the chat. Waiting chats count in
  the dashboard's "Needs you" and the Chats badge. The Questions page is unchanged.
- **The agent's owner sees and directs the chat** even when someone else started it (the work runs on their machine;
  they can direct that agent on tasks). Visibility is: the starter, the agent's owner, the project's managers, admins.
- **The first message is the task description** for the engine, and the chat's title is a short summary the agent
  gives (falling back to the first message's first line).
- **Agent choice uses the task rules:** `can_use_agent` and the agent's binding to the project; "any free agent"
  picks among the agents the person may use.

## Constraints

- Same permissions as tasks: viewers never start chats; read-only project members can't.
- Light and dark mode, desktop and phone, no sideways scrolling.
- Runner: no new runner capability is needed beyond what tasks already use (workflow/1, branch/1, model/1, steer/1).

## Left to the builder

- How the "chat" mark is stored and filtered everywhere tasks are listed or counted.
- How the chat view reuses the task's Activity, question, document and step components.
- The summary title and the end dialog's description text (an AI summary is fine when the project has AI on; a plain
  template otherwise).
- Realtime updates for the chat list and view (reuse the task events).
