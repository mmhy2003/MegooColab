# MC-94: Trigger prompts

This design goes with mockup **v2** ("Trigger prompts v2 (final): Triggers tab, editor, firings and the triggered chat").

## Goal

A manager sets up a **trigger** in a project: "when this happens, send this prompt to an agent". Each time the event happens, MegooColab starts a freestyle chat with the prompt and a description of what happened, so the agent can work in the project (change code, open pull requests, manage the board) without anyone asking it by hand.

## Decisions

| Decision | Chosen | Why, and what was rejected |
|---|---|---|
| What a triggered agent may do | **A freestyle chat** per firing (your answer). | Rejected: a read-only cron-like run (cannot change code), a choice per trigger (more to build and explain), a board task run through the full workflow (every firing waits for approvals). |
| Events in this version | **All nine** in one design (your answer). | Rejected: a first version with six events and three follow-up tasks. So there are no follow-up tasks. |
| Where it lives | **Its own "Triggers" project tab**, after Crons (your answer). | Rejected: one "Automations" tab with crons, and a tab inside Settings. |
| After the agent replies | **A setting per trigger, default "End the chat"** (your answer). | Rejected: always end, always keep open, default open. |
| How the prompt learns what happened | No placeholders. MegooColab adds a **"What happened"** block under the prompt. | A template syntax is more to learn and to validate, and the block already carries the keys and links. |
| Loops | What a triggered chat does **never fires a trigger**, and one trigger fires **at most 20 times an hour**. | Both were shown in the mockup and accepted. |
| "Task finished" | A story, task or bug **reaches a Done column**, by its workflow or moved by a person. | It covers tasks with and without a workflow. Subtasks, epics and chat rounds never fire task events. |
| In whose name a chat starts | **The person who last saved the trigger** ("runs as"). | A chat needs a starter for rights, visibility and notifications. Whoever last edited the prompt or agent is the one who vouches for it. Pause and resume do not change it. |
| Rights | Members read; managers of the project and admins write. | The same as crons. |

## The nine events

Task events fire only for board tasks of type story, task or bug. Each can be narrowed by type (at least one) and by one label.

| Id | Shown as | Fires when | Extra setting | Where the code hooks in |
|---|---|---|---|---|
| `task_finished` | A task is finished | The task enters a Done-category column from a column that is not Done. | types, label | The two `status_changed` sites: `tasks/service.py` (a person or an agent moves it) and `workflow/engine.py::move_to_category` (the workflow). |
| `task_created` | A task is created | A board task comes to exist: created by a person, an agent, a cron, approved follow-ups or a known-bug offer, or a chat round is added to the board. | types, label | `tasks/service.py::create_task`, and `chats/service.py::decide_board`. |
| `task_moved` | A task is moved to a column | The task enters the chosen column. | column, types, label | The same two `status_changed` sites. |
| `task_needs_person` | A task needs a person | The task's workflow escalates. Approvals and questions do not count. | types, label | `workflow/engine.py::escalate`. |
| `sprint_started` | A sprint is started | A sprint goes from planned to active. | none | `sprints/service.py::start`. |
| `sprint_completed` | A sprint is completed | A sprint is completed. | none | `sprints/service.py::complete`. |
| `epic_completed` | An epic is completed | A task whose parent is an epic enters Done, and now every task of that epic is in a Done column. | none | Checked inside the task-moved hook. |
| `cron_found` | A cron finds something | A cron run ends `done` with at least one finding. | one cron, or any cron | `crons/turns.py::on_run_finished`. |
| `pr_merged` | A pull request is merged outside a task | A repository's own webhook delivers a merged pull request that matches no task (no `megoo/<KEY>` branch, no link, not tracked) and whose base is the repository's default branch. | none | `git/activity.py::record`, at the point where it finds no task. `git/events.py` also reads the base branch of a merged pull request (GitHub, Gitea and GitLab). |

The two sprint events are offered only in projects with sprints enabled.

## Architecture

### Backend: a new module `backend/app/triggers/`

- **`models.py`**: `Trigger` and `TriggerFiring` (see Data and interfaces).
- **`events.py`**: a registry with one entry per event. Each entry has four small functions:
  - `validate(config)`: checks the event's settings when a trigger is saved.
  - `matches(config, payload)`: applies the filters.
  - `describe(db, payload)`: returns the short subject for the history ("MC-100 finished · merged", with a link) and the "What happened" text.
  - `latest(db, trigger)`: the newest thing that matches, for "Try it".
- **`emit.py`**: one function per hook, for example `task_moved(db, task, from_column, to_column, actor)`. A hook site calls exactly one of them. `emit`:
  1. returns at once when the project is not active, or when the change comes from a triggered chat (the loop guard, below);
  2. finds the project's unpaused triggers for the event and applies `matches`;
  3. inserts one `TriggerFiring` row per match, with status `pending` and the described subject and text.
  It runs in a savepoint and logs any error, so a trigger can never fail or undo the action that caused it. It starts no chat.
- **`fire.py`**: `trigger_loop`, started in `main.py` beside `cron_loop`, because runs can only be sent to runners from the API process. Every 5 seconds it takes the pending firings (`FOR UPDATE SKIP LOCKED`) and for each one:
  1. skips it when the trigger was paused meanwhile (`paused`);
  2. skips it when the "runs as" person is inactive or may no longer start chats in the project (`owner_gone`);
  3. skips it when the trigger already started 20 chats in the last hour (`rate_limited`);
  4. picks the agent: the chosen one while it is usable, or any free agent the "runs as" person may use (online first, then least busy, as chats do). None gives `no_agent`;
  5. starts a freestyle chat titled `<trigger name> · <subject>` whose first message is the trigger's prompt, marks the firing `started`, stores the chat and the agent, and dispatches the run.
- **`context.py`**: a context provider (the mechanism `chats/context.py` already uses). For a freestyle turn of a triggered chat it adds a section `## What happened` with the firing's text wrapped as untrusted, and two sentences saying that a trigger started this chat and nobody may be watching. No methodology text changes.
- **`service.py`, `schemas.py`, `router.py`**: create, read, update, pause, resume, delete, try and the firing history, with an audit record for each write, following `crons/`.

### Changes to existing backend code

- **Hook sites** (one `emit` call each): `tasks/service.py`, `workflow/engine.py`, `chats/service.py::decide_board`, `sprints/service.py`, `crons/turns.py`, `git/activity.py`.
- **`chats/service.py`**: the part of `start_chat` that creates the chat and its first round becomes a function both `start_chat` and `fire.py` call. `ChatOut` gets `trigger` (see below).
- **`workflow/freestyle.py::handle_turn_end`**: where a turn would wait for the next message, a chat started by a firing with `keep_open = false` is ended instead. The round finishes as it does on "End chat", with no "Chat finished" notification. A turn that asked a question, or a turn that failed, leaves the chat open.
- **`workflow/freestyle.py::_notify_replied`**: for the firing's own turn, the "agent replied" notification follows the trigger's "Tell me" switches. Later turns of a kept-open chat notify as any chat does.
- **`git/events.py`**: a merged pull request's event carries its base branch.

### The loop guard

A freestyle turn's board changes already run with `event_origin` set to its chat. `emit` looks that chat up and returns when a firing started it. So a triggered agent that creates, moves or finishes tasks, or starts and completes sprints, fires nothing. A pull request a triggered agent merges from its chat's own `megoo/<KEY>` branch belongs to that chat's round, so it is not "outside a task". The limit of 20 chats an hour per trigger bounds everything else.

### Frontend

- **`app/(app)/projects/[key]/layout.tsx`**: a "Triggers" tab after "Crons".
- **`app/(app)/projects/[key]/triggers/page.tsx`** and **`[triggerId]/page.tsx`**: the list and one trigger with its firings, following the two cron pages.
- **`components/triggers/TriggerList.tsx`**: each row shows the name and the prompt's first line, the event in words with its filter, the last firing with its result, and Pause or Resume.
- **`components/triggers/TriggerEditor.tsx`**: the dialog of the mockup. The fields under "When" change with the event: column, cron, "Only for" types and label, or the webhook note. Below the prompt it shows an example of the "What happened" block for the chosen event.
- **`components/triggers/FiringList.tsx`**: the history table: fired at, what happened, agent, result with a link to the chat.
- **`lib/triggers.ts`**: hooks, types and the texts for events, results and skip reasons.
- **Chats**: `ChatList` and the chat header show a "Trigger" chip. The first message is shown as "Trigger <name> · runs as <person>" with the "What happened" block under the prompt. `ChatsPage` gets a switch "Chats started by triggers" (on by default, remembered like the state filter). An ended triggered chat says "This chat ended when the agent replied."

## Data and interfaces

### Tables (one migration)

**`triggers`**

| Column | Type | Notes |
|---|---|---|
| `project_id` | FK projects, cascade | indexed |
| `name` | string(100) | |
| `event` | string(30) | one of the nine ids |
| `config` | JSONB | `{task_types?, label_id?, column_id?, cron_id?}`; only the keys the event uses |
| `prompt` | text | at most 8,000 characters, the limit of a chat message |
| `any_agent`, `agent_id` | bool, FK agents set null | as on crons |
| `keep_open` | bool, default false | "After the agent replies" |
| `notify_reply`, `notify_problems` | bool, default true | "Tell me" |
| `paused` | bool, default false | |
| `owner_id` | FK users, set null | "runs as": set on create and on every edit |
| `created_by`, `created_at`, `updated_at` | | |

**`trigger_firings`**

| Column | Type | Notes |
|---|---|---|
| `trigger_id` | FK triggers, cascade | indexed with `created_at` |
| `event` | string(30) | |
| `subject` | JSONB | `{kind, label, title, link, note}` for the history row |
| `what` | text | the "What happened" block, written once when the event happens (at most 6,000 characters) |
| `status` | string(10) | `pending`, `started` or `skipped` |
| `skip_reason` | string(100) | `no_agent`, `owner_gone`, `rate_limited`, `paused` |
| `agent_id` | FK agents, set null | |
| `chat_id` | FK chats, set null, unique | |
| `keep_open` | bool | copied from the trigger when it fires |
| `tried` | bool | a "Try it" firing |
| `created_at`, `started_at` | | |

A referenced column, label or cron lives in `config`, not in a foreign key. When it is deleted the trigger stops matching and is shown as broken ("its column was deleted"). It never silently widens to "any".

### REST (prefix `/api/projects/{key}/triggers`)

| Method and path | Does | Who |
|---|---|---|
| `GET /` | list, each with its last firing | members |
| `POST /` | create | managers, admins |
| `GET /{id}` | one trigger | members |
| `PATCH /{id}` | edit; the editor becomes "runs as" and the agent must be one they may use | managers, admins |
| `DELETE /{id}` | delete with its firings; the chats stay | managers, admins |
| `POST /{id}/pause`, `/resume` | pause or resume | managers, admins |
| `POST /{id}/try` | fire once now on the newest thing that matches | managers, admins |
| `GET /{id}/firings?limit=` | newest first, 50 by default | members |

- `TriggerOut` adds to the stored fields: `agent`, `owner`, `broken` (null or `column_deleted`, `label_deleted`, `cron_deleted`), `last_firing` and `try_subject` (the label for "Try it on MC-100", or null).
- `FiringOut`: `id`, `created_at`, `subject`, `agent`, `chat_id`, `result` and `excerpt`. `result` is one of `starting`, `waiting_agent`, `working`, `question`, `replied`, `failed`, `skipped`, worked out from the firing's status and its chat's state. `excerpt` is the reply's first lines, the question, or the skip reason.
- `ChatOut.trigger`: null, or `{id, name, what, keep_open}`.
- Errors are 422 with a code, as elsewhere: `invalid_event`, `invalid_config`, `invalid_column`, `invalid_label`, `invalid_cron`, `no_task_types`, `agent_not_available`, `nothing_to_try`.
- Pause, resume and delete also work on a finished project, as for crons.

## Error handling and edge cases

- **A trigger never breaks the action.** `emit` runs in a savepoint; an error is logged and the action goes on.
- **No usable agent, or the "runs as" person is gone:** the firing is skipped with the reason. With "Tell me when a firing is skipped or fails" on, the "runs as" person and the project's managers are told, with a link to the trigger. For `rate_limited` they are told once an hour per trigger, not once per firing.
- **The agent is offline:** the chat is created and its turn waits, as for any chat. The firing shows "Waiting for the agent".
- **The turn fails:** the chat stays open so a reply can retry it, whatever "After the agent replies" says. The firing shows "Couldn't finish".
- **The agent asks a question:** the chat stays open until it is answered, and the usual "needs you" notification goes out.
- **The trigger is deleted while a chat works:** the chat loses its trigger link and carries on as an ordinary chat.
- **Several triggers match one event:** each fires, and each starts its own chat.
- **One move, several events:** a task moved into a Done column can fire `task_moved`, `task_finished` and `epic_completed`.
- **An epic is completed again** (a task reopened, then finished): it fires again.
- **Approved follow-ups create several tasks at once:** `task_created` fires for each, within the hourly limit.
- **A finished or archived project:** nothing fires.
- **"Try it":** counts toward the hourly limit and works on a paused trigger. It is not offered for `pr_merged`, because pull requests outside a task are not stored, and it is hidden when nothing matches yet.
- **`pr_merged` needs the repository's own webhook.** The editor says whether it is set up. A delivery through a connection's old shared address fires nothing.
- **Untrusted text:** task titles, cron findings and pull request titles reach the agent only inside the untrusted "What happened" block. The prompt itself is the manager's own words and is delivered as a person's message.
- **A triggered agent merges a pull request from a branch that is not its chat's own:** this can fire `pr_merged`. The hourly limit bounds it.

## Testing

Test-first, as the project does.

**Backend** (`backend/tests/triggers/`, plus additions where hooks were added):
- each of the nine events: the hook writes a firing for a matching trigger and none for a non-matching one (type, label, column, cron, paused, inactive project, subtask, epic, chat round);
- `epic_completed` fires only when the last task finishes; `pr_merged` only for an untracked pull request into the default branch, for GitHub, Gitea and GitLab payloads;
- the loop guard: a board change made by a triggered chat's turn writes no firing, and the same change by a person's chat does;
- `fire.py`: the chat, its title and first message; the agent choice; each skip reason; the hourly limit and its single notification;
- the context provider: the block is present, wrapped as untrusted, only for triggered chats;
- turn end: the chat ends by default, stays open with `keep_open`, after a question and after a failure; the notifications follow the switches;
- the API: rights for member, manager and admin, validation codes, "runs as" changing on edit, `try`, a broken reference, cascade on delete;
- a failing `emit` does not fail the action.

**Frontend** (vitest):
- `TriggerEditor` shows the right fields for each event and sends the right body;
- `TriggerList` and the trigger page: rows, results, skip texts, Pause and Resume, "Try it", rights;
- chats: the chip, the first message with its block, the "Chats started by triggers" switch, the ended note;
- the layout test gets the new tab. `api-types.ts` is regenerated, then `tsc --noEmit`, eslint and the full `npm test`.

## Out of scope

- Other kinds of action: a read-only report run, or opening a board task and running the workflow on it.
- Placeholders or templates in the prompt.
- Events beyond the nine (for example a design approved, a review that found problems, a pull request opened).
- Triggers across projects or for the whole organization, and outgoing webhooks.
- A line on the task's Activity saying that a trigger fired.
- Cleaning up the worktrees of ended chats (triggered chats behave as other chats here).
