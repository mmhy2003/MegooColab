# Freestyle chats — design

Status: approved by the owner on 2026-11-06 ("go" to the proposal in chat; "approved" to the mockup). Calls marked
*(builder's call)* were made while writing this up and after a builder check against the code.

## Why

A chat today always runs the full workflow: talk → design → plan → build (with step reviews) → final review →
finish. That suits a feature. It does not suit "do a new release" or "rename this file": the owner's SLW-3 chat asked
for a release, the agent followed the repository's own CLAUDE.md and switched to a `release/…` branch, and the next
read-only review run refused (`git_state_unreadable`) and escalated. The owner wants to choose, per chat, between the
workflow and a **freestyle** conversation in which the agent simply does what it is told, one reply at a time.

## Goals

- When starting a chat, choose **Workflow** (today's chat, the default) or **Freestyle**.
- In a freestyle chat each message is one turn: the agent works with write access in the chat's own worktree,
  continues its session, replies, and waits for the next message.
- No design or plan documents, no reviews, no enforcement checks, no automatic finishing step, no escalations.
- The agent may switch or create branches, commit, merge and push when asked (it uses the developer's own git setup,
  as the finish step does today).

## Non-goals

- Switching a chat between modes after it starts.
- A project setting that forbids freestyle (owner: anyone who may chat may choose it).
- A "Stop" button for a running turn (End chat still stops it, as today).
- Freestyle for board tasks. Only chats.
- Any runner change (see "Runner").

## Anti-goals

- A workflow chat or a board task behaving differently than today.
- A freestyle chat ever getting stuck with nothing to click: every state must be left by sending a message or ending
  the chat.
- Freestyle chats flooding **Needs you**: a freestyle chat waiting for the next message is normal, not a request.

## Starting a chat

- The New chat dialog gets a choice, **How should the agent work?**:
  - **Workflow** — "Talks it through, writes a design and a plan for you to approve, builds it step by step with
    reviews, then finishes as the project is set up to." (default)
  - **Freestyle** — "Does what you ask, one reply at a time, with no design, plan or reviews. It can change files,
    switch branches, commit and push when you ask."
- *(builder's call)* The last choice is remembered in this browser (per-viewer convenience, `localStorage`, read and
  written in try/catch); with nothing remembered it is Workflow.
- `POST /api/chats` takes `mode: "workflow" | "freestyle"` (default `"workflow"`). The chat stores it (`chats.mode`,
  a new column, `workflow` for existing rows). `ChatOut` returns it.

## How a freestyle chat runs

### The round

A freestyle chat has exactly **one round** (a task kept off the board, as every chat round is). It never starts a
new round: every message continues it. Its workflow row:

- `driver = runner`, `enforcement = unenforced`, `stage = build` *(builder's call: closest to "working"; nothing
  reads a freestyle round's stage for progress)*, `current_step = None`.
- Started by a new `engine.start_freestyle(db, user, task)` instead of `engine.start`; same checks as `start`
  (type, usable agent, not already active).

### The turn run

- A new run role **`RunRole.freestyle`**: policy `workspace`; resumable (session key `"freestyle"`, not in
  `FRESH_ROLES`); not in `R1_ROLES` (it may change the repository).
- Its prompt comes from a new default methodology text **`freestyle`** (`methodology_texts/defaults/freestyle.md`),
  plus the usual context sections (the task, its thread of messages, memory, Knowledge Base, instructions). The text
  tells the agent:
  - it is in a direct conversation with the person: do what the latest message asks, then reply and end its turn;
  - it works in the chat's worktree, which starts on the branch `megoo/<KEY>-…`; it may create or switch branches,
    commit, merge, push and open pull requests when asked, with the developer's own git credentials, never putting
    tokens in URLs or printing credentials;
  - nothing it does is reviewed: say plainly what it changed, which branch it is on, and anything left undone;
  - it may ask with `ask_human` when it truly cannot proceed;
  - it must not edit `.megoocolab/`.
  - *(builder's call)* if it checks out a branch other than its own `megoo/<KEY>-…`, it switches back to its own
    branch before ending the turn, so that branch is free for the developer to check out (git allows one checkout of
    a branch, and the chat's worktree is never removed); it never checks out a branch that is checked out elsewhere
    (create new branches from it, or push and open a pull request instead).
- MCP tools the role may use (`TOOL_ROLES`, `KB_TOOL_ROLES`): `ask_human`, `record_decision`, `record_tests`,
  `kb_write` *(builder's call: freestyle has write access like the implementer, which may write to the Knowledge
  Base)*, plus every tool open to all roles today (memory, Knowledge Base reads, tasks, comments…). Not
  `submit_design`, `submit_plan`, `complete_step`, `submit_review`, `report_finish`, `report_pr_fix`,
  `submit_pr_review`, `show_mockup`.
- **Each message is delivered as today's agent messages are**: a comment addressed to the agent
  (`create_comment(..., to_agent=True)`), taken by the next run at its start (`instructions.take_waiting`), or read
  straight away while a turn runs (the existing "tell").
- **Freestyle's own wording for messages.** Today's framing (`instructions.RULE`, `STEER_PREFIX`) speaks of "the
  approved design or plan" and "a reviewer"; a freestyle run gets its own wording instead ("The person you are
  working with sent you this. Do what it asks."), leaving the workflow wording unchanged. The first message stays the
  task's description, framed as today.
- **A resumed freestyle session is not re-sent earlier messages.** Today a resumed run also gets every previously
  delivered message again (`instructions.kept_in_mind`); for freestyle that would repeat the whole conversation on
  every turn. A freestyle run resuming its own session gets only the new messages.
- **A fresh freestyle session gets the conversation so far.** The first turn, a lost session, and agent programs
  that can't resume start a fresh session; today's prompt would give it the person's messages (capped) but none of
  the agent's own replies (`context._thread` leaves both out). A freestyle prompt instead carries a **"Conversation
  so far"** section: in order, each of the person's messages and, for each earlier turn, the agent's last message
  (its reply), newest kept when it must be cut, within 12,000 characters, the agent's replies wrapped as untrusted.
  *(builder's call)*

### When a turn ends (`ROLE_HANDLERS[freestyle]`)

- The agent asked (`ask_human`): wait for the answer (`Needs.question`), as today; the answer resumes the session.
- An answer arrived while it ran: deliver it, as `_handle_brainstorm_or_plan` does.
- Otherwise: **wait for the next message** — a new `Needs.reply`, `status = waiting_human`.
- **A failed turn, or one cancelled by nothing a person did** (a lost connection), does not retry and never
  escalates: it also waits for the next message (`Needs.reply`). The failure stays visible in the conversation as
  today ("<agent> failed: <reason>"). `wf.failures` is not counted for freestyle.
- **A message still waiting when a completed turn ends starts the next turn on its own** (it was sent while the turn
  was queued, or couldn't be read while it worked): the chat never says "waiting for your reply" with the person's
  message unread. After a **failed** turn it does not: the round waits with `Needs.reply`, and the waiting message
  goes with the next turn the person's next message starts, so a turn that always fails can't loop. *(builder's
  call)*
- If handling a turn's end itself fails (today's `engine_error` escalation), a freestyle round waits with
  `Needs.reply` instead of escalating.
- A turn cancelled by a person pauses the round, as today; a message resumes it (the existing "restart").
- A turn cancelled because the agent's owner was deactivated pauses the round as today; nothing can run it again,
  so only End chat leaves it. (Accepted: the agent is gone.)
- No nudge, no `no_output` escalation: a turn that says nothing still waits for the next message.

### What a message does (chat intent)

| The freestyle round | Intent | What happens |
|---|---|---|
| a turn is running | `tell` | read straight away, as today |
| waits for an answer (`Needs.question`) | `answer` | answers the question, as today |
| waits for the next message (`Needs.reply`) | **`turn`** (new) | the message becomes a comment to the agent and a new freestyle run is queued; it takes the message at its start |
| paused | `restart` | as today |
| the chat ended | `closed` | as today |

`new_round`, `changes` and `retry` never apply to a freestyle chat (it has no rounds after the first, no documents,
no escalations). Composer line for `turn`: "<agent> starts working on your message."

### Ending a freestyle chat

- End chat asks first, as every chat does now (while a turn runs, the existing "Stop the agent…" text).
- It cancels a running turn, then **finishes the round** (`status = finished`, `stage = done`, `finished_at` set,
  no finishing outcome) instead of pausing it: nothing waits in a freestyle chat. The "Add this to the board?" dialog
  then defaults to the Done column, as for a finished round.

## What people see

### The chat

- Header: a **Freestyle** chip where a workflow chat shows the progress line (Talk → Design → Plan → Build →
  Finish), on desktop and in the phone's one-line progress.
- States (`ChatState`), shown in the header, the chat list and the dashboard:
  - `working` — "working" (a turn is queued or running; `offline` as today when its runner isn't connected);
  - `reply` — "waiting for your reply";
  - `question`, `finished`, `ended` as today.
- The conversation shows the messages and the agent's activity as today. A freestyle round shows no Design, Plan or
  Decisions sections unless something is in them (they will be empty).

### Needs you, counts and notifications

- `Needs.reply` is **not** a Needs you item, not counted in the chats' waiting badge, not marked NEEDS YOU, and not
  a "needs you" notification. A freestyle question (`Needs.question`) is, as today.
- **Each turn's end notifies** the chat's starter once: a new notification kind `agent_replied`, title
  "<agent> replied in <chat title>", linking to the chat. Defaults: in-app on; email, push and Telegram off. It is
  marked read when they reply (the existing `read_by_acting`). *(builder's call: a long freestyle turn, such as a
  release, otherwise finishes unnoticed.)*

### Elsewhere

- A freestyle round added to the board is an ordinary finished task.
- Workflow chats, tasks, the board and the dashboard are otherwise unchanged.

## Runner

No change. The runner ignores the run role; a `workspace` run already lets the agent change files and branches, and
the read-only "must start on the task branch" check (`git_state_unreadable`) applies only to read-only runs.

## Data

- `chats.mode` String(10), not null, default `workflow` (Alembic migration; existing rows `workflow`).
- `RunRole.freestyle`, `Needs.reply`, `Kind.agent_replied` are values of String columns: no schema change.
- The methodology text `freestyle` is a new default, seeded the way the other defaults are.

## Tests that matter

- Starting a freestyle chat queues one `freestyle` run (workspace policy) and no brainstorm run.
- A completed turn waits with `Needs.reply`; a message then queues the next turn and the message is taken at its
  start; a resumed turn's prompt does not repeat earlier messages.
- A failed turn waits with `Needs.reply` and never escalates, also after 3 failures in a row.
- `ask_human` in a freestyle turn waits for the answer; the answer resumes it.
- A freestyle chat waiting for a reply is not in Needs you, the waiting count or NEEDS YOU; it notifies
  `agent_replied` once per turn.
- Ending a freestyle chat finishes the round (also while a turn runs); a workflow chat still pauses as today.
- A message to a freestyle chat never starts a new round.
- The New chat dialog sends the mode; the header shows Freestyle; the states and the composer line read as above.
- A fresh freestyle session's prompt holds the conversation so far (the person's messages and the agent's replies);
  a resumed one doesn't repeat it.
- A message left waiting when a completed turn ends starts the next turn; after a failed turn it doesn't.
- A freestyle run's messages use the freestyle wording; a workflow run's are unchanged.
- An end-to-end test: a freestyle chat with the fake agent, two turns, then End chat.

## Left to the builder

File layout, names of helpers, exact copy beyond what is quoted here, and how the freestyle text is worded beyond
the points listed.
