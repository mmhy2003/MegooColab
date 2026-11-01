# Agent chats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person starts a chat with an agent on one project. It runs the task workflow (talk → design → plan → build →
finish) as a conversation, can go round again, and at the end of each round offers to become a task on the board. Chats
appear on a Chats page, in a project tab, and on the dashboard.

**Architecture:**
- **Data.** A new `chats` table holds the conversation's metadata. Each round is a `Task` row with `chat_id`,
  `chat_round` and `in_chat=true`.
- **Engine.** Every round runs on the existing workflow engine unchanged, apart from three hooks: no step subtasks,
  notifications that link to the chat, and context from earlier rounds.
- **Hiding.** One predicate, `on_board()`, keeps `in_chat` rows out of every task listing, count and search.
- **"Add to the board"** clears the flag on the round's own row.
- **The chat API** turns a typed message into the action the round is waiting for: an answer, a rejection, a "tell the
  agent" message, a restart, or a new round.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic, Next.js 16 + TanStack Query + Vitest + Playwright. No runner change.

**Spec:** `docs/superpowers/specs/2026-11-01-agent-chats-design.md`

## Global Constraints

- **Visibility:** a chat (and every round task's API) is visible to the person who started it, the agent's owner, the
  project's managers and admins. Anyone else gets 404 `not_found`.
- **Who may act:** only people passing WF-6 (`engine.require_actor`) may send messages, approve, end a chat or decide
  about the board. Anyone else gets 403 `cannot_act_on_workflow`.
- **Who may start one:** viewers and read-only project members never start chats (the same write access as creating a
  task, `get_project_for(write=True)`). The agent must pass `can_use_agent` and be bound to the project.
- **Hiding:** a round with `in_chat=true` never appears in board, backlog, sprints, sprint points and burndown, column
  counts, dashboard task numbers, the finished-by-agents/people series, workflows by stage, recent activity, search,
  MCP `list_tasks`, or assignment notifications.
- **Showing anyway:** such a round **does** feed the Knowledge Base (WF-9 filing) and memory, and it appears in Needs
  you, Running now and the Chats card.
- **Numbers:** a round takes the project's next task number (`next_number`).
- **Plan steps:** chat rounds don't create plan-step subtasks. Adding a round to the board creates them, each in the
  state its step reached.
- **Copy, exact strings:**
  - `Add this to the board?`
  - `No, just end it`
  - `Create task`
  - `End chat`
  - `New chat`
  - `All chats`
  - `Open chats`
  - `waiting on you`
  - `Starts a new round: the agent talks it through, then design, plan, build and finish again.`
- **Light and dark mode, desktop and phone, no sideways scrolling.**
- **No new dependencies.** Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A message sent while the round's state changes** (for example, the agent submits the plan between the composer
   loading and the send) must do what the *current* state calls for, never act on a stale one. Owned by Task 4; test
   `test_message_follows_the_state_at_send_time`.
2. **A hidden round reached by its key** (from a notification, Knowledge Base or memory link, or a typed URL) must open
   the chat for people who can see it and 404 for everyone else. It must never show as a plain task page. Owned by
   Task 1 (API) and Task 7 (redirect); tests `test_round_task_is_404_for_people_who_cannot_see_the_chat` and
   `redirects a chat round's task page to the chat`.
3. **Adding a round that is still in human code review** to the board puts it in the review column, and it must keep
   tracking the pull request afterwards. Owned by Task 6; test `test_round_in_human_review_goes_to_the_review_column`.
4. **Two people answering the same waiting chat** (an owner and a manager) must get first-wins behaviour (the existing
   409s), not a double answer or a double rejection. Owned by Task 4; test `test_second_reply_to_a_decided_plan_is_409`.
5. **A new round while the previous round's pull request is still open** must branch from that round's branch. Owned
   by Task 5; test `test_next_round_branches_from_an_open_pr`.

---

## File map

| File | Responsibility |
|---|---|
| `backend/app/chats/models.py` | `Chat`, `ChatStatus` |
| `backend/app/chats/schemas.py` | `ChatIn`, `ChatOut`, `RoundOut`, `MessageIn`, `MessageOut`, `BoardIn`, `BoardDefaults` |
| `backend/app/chats/service.py` | create, list, visibility, state, intent, message, rounds, end, board |
| `backend/app/chats/router.py` | `/api/chats…` |
| `backend/app/chats/context.py` | the "Earlier rounds of this chat" context provider |
| `backend/app/tasks/models.py` | `Task.chat_id`, `chat_round`, `in_chat`, `chat_board` |
| `backend/app/tasks/visibility.py` | `on_board()` |
| migration `<rev>_agent_chats.py` | the table and columns |
| filters in tasks/projects/dashboard/sprints/search/mcp | `on_board()` everywhere listed |
| `backend/app/workflow/{documents,engine}.py`, `instructions.py` | no subtasks; notifications to the chat; instructions across rounds |
| `backend/app/dashboard/{chats.py,needs.py,agents.py,tasks.py}` | the Chats card, tile, needs/running tags, the finished series |
| `frontend/src/lib/chats.ts` | queries, types, state and intent copy |
| `frontend/src/components/chats/*` | `ChatList`, `NewChatDialog`, `ChatView`, `ChatComposer`, `BoardDialog`, `RoundDivider` |
| `frontend/src/app/(app)/chats/…`, `projects/[key]/chats/page.tsx` | the pages |
| `frontend/src/components/dashboard/{ChatsCard.tsx,Kpis.tsx,FinishedChart.tsx,NeedsYou.tsx,RunningNow.tsx}` | the dashboard |
| `frontend/e2e/chats.spec.ts` | end to end |

---

### Task 1: Chats and rounds, created and seen by the right people

**Files:**
- Create: `backend/app/chats/{__init__,models,schemas,service,router}.py`, `backend/app/tasks/visibility.py`
- Create: migration `agent_chats` (down_revision: the current head `de9afbdf9a94`)
- Modify:
  - `backend/app/tasks/models.py`
  - `backend/app/tasks/service.py` (`get_task_for`)
  - `backend/app/main.py` (router)
  - `backend/app/tasks/schemas.py` (`TaskOut.chat_id`)
- Test: `backend/tests/chats/test_chats.py`

**Interfaces — Produces:**
- `class ChatStatus(StrEnum)`: `open`, `ended`.
- `class Chat(IdMixin, Base)`, table `chats`, with columns:
  - `project_id` FK projects CASCADE
  - `started_by` FK users SET NULL
  - `agent_id` FK agents SET NULL
  - `title: str` (String 200)
  - `status: ChatStatus` (String 10, default open)
  - `created_at`, `last_activity_at` (server default now)
  - `ended_at`
  - index on `(project_id, last_activity_at)`
- New `Task` columns:
  - `chat_id` FK chats SET NULL, indexed
  - `chat_round: int | None`
  - `in_chat: bool` (server default false, not null)
  - `chat_board: str | None` (String 10; `added` or `declined`)
- `def on_board() -> ColumnElement[bool]` in `tasks/visibility.py` returns `Task.in_chat.is_(False)`.
- `async def can_see_chat(db, user, chat: Chat) -> bool`. True when the user is the starter, the agent's owner, a
  manager of the project (`engine.manages`), or an admin.
- `get_task_for`: for a task with `in_chat`, it loads the chat and raises 404 `not_found` unless `can_see_chat`.
  `TaskOut` gains `chat_id: uuid.UUID | None` (set only while `in_chat`).
- `async def start_chat(db, user, project_key: str, agent_id: UUID | None, message: str) -> Chat`. It:
  1. checks write access to the project;
  2. picks the agent: the given one if `can_use_agent` and bound to the project (else 422 `agent_not_available`),
     otherwise `pick_agent`;
  3. creates the chat (title is the message's first line, cut to 120 characters);
  4. creates round 1 with `create_round(db, user, chat, message)`.
- `async def pick_agent(db, user, project) -> Agent`. Among the agents the user may use that are bound to the project,
  it takes the first by: online before offline, then fewest active runs, then name. If there are none, it raises 422
  `no_agent`.
- `async def create_round(db, user, chat, message: str, *, branch_from: str | None = None) -> Task`. It creates a task
  with `TaskCreate(title=chat.title (round 1) or the message's first line, type=task, description_md=message,
  assignee_agent_id=chat.agent_id, column_id=first before column)` and `in_chat=True`, `chat_id`,
  `chat_round=max+1` and `branch_from`. Then it calls `engine.start(db, user, task)` and sets
  `chat.last_activity_at`. `create_task` must not send assignment notifications for `in_chat` tasks: it gets a keyword
  `in_chat: bool = False` and sets the fields before `notify_assigned`, which it skips.
- `ChatOut` fields:
  - `id`, `project_key`, `title`, `status`
  - `agent: {id, name, program} | None`
  - `started_by: UserOut | None`
  - `created_at`, `last_activity_at`
  - `state: ChatState`
  - `rounds: list[RoundOut]`
  - `can_act: bool`
- `RoundOut` fields:
  - `n`, `key`, `title`
  - `stage`, `status`, `needs`
  - `current_step`, `steps_total`
  - `finish_outcome`, `pr_url`, `branch`, `branch_from`
  - `board: Literal["pending","added","declined"] | None`. `pending` means the round finished or the chat ended with
    no decision yet; `None` means it is still going.
- `ChatState = Literal["talking","question","design_approval","plan_approval","building","in_review","human_code_review","escalation","offline","finished","ended"]`.
  `chat_state(chat, round_task, wf, agent_online: bool) -> ChatState` uses the latest round. The order of the checks:
  1. `ended` when the chat is ended;
  2. `finished` when the workflow is finished;
  3. from `needs`: question, design_approval, plan_approval, escalation or human_code_review;
  4. `offline` when a run is queued and the agent is offline;
  5. `in_review` when the stage is review;
  6. `building` when the stage is build;
  7. otherwise `talking`.
- Router:
  - `POST /api/chats` (201) takes `ChatIn{project_key, agent_id?, message (1..8000)}`;
  - `GET /api/chats?project=KEY` returns the visible chats. Chats waiting on the viewer (state in question,
    design_approval, plan_approval or escalation, and `can_act`) come first, then by `last_activity_at` descending;
  - `GET /api/chats/{id}` (404 unless visible).

- [ ] **Step 1: Write the failing tests** in `tests/chats/test_chats.py`. Build the world like
  `tests/tasks/test_agent_messages.py::_world`: an owner with a bound agent, plus another member. Stub the dispatch the
  way the engine tests do.

```python
async def test_starting_a_chat_creates_a_hidden_round_running_the_workflow(client, db):
    r = await client.post("/api/chats", json={"project_key": "PAY", "message": "Fix the empty email crash\nIt 500s."})
    assert r.status_code == 201
    chat = r.json()
    assert chat["title"] == "Fix the empty email crash" and chat["state"] == "talking" and chat["status"] == "open"
    [rnd] = chat["rounds"]
    assert rnd["n"] == 1 and rnd["stage"] == "brainstorm" and rnd["board"] is None
    board = (await client.get("/api/projects/PAY/tasks")).json()
    assert all(t["key"] != rnd["key"] for t in board)            # hidden
    assert (await client.get(f"/api/tasks/{rnd['key']}")).json()["chat_id"] == chat["id"]

async def test_any_free_agent_picks_a_usable_bound_agent(client, db)       # agent omitted → chat.agent.id == the owner's agent
async def test_an_agent_the_person_may_not_use_is_refused(client, client_factory, db)  # 422 agent_not_available
async def test_viewer_cannot_start_a_chat(client, client_factory, db)       # 403
async def test_chat_is_visible_to_starter_owner_managers_admins_only(client, client_factory, db)
    # other member: GET /api/chats → [], GET /api/chats/{id} → 404
async def test_round_task_is_404_for_people_who_cannot_see_the_chat(client, client_factory, db)
async def test_no_assignment_notification_for_a_chat_round(client, db)    # notifications list empty for the agent's owner
```

- [ ] **Step 2: Run** `uv run pytest tests/chats/test_chats.py -q`. Expected: FAIL (no module).
- [ ] **Step 3: Implement** the models and migration (against `megoo_migrate`, named constraints, a downgrade round
  trip), then the service and router above.
- [ ] **Step 4: Run** `uv run pytest tests/chats tests/tasks -q`. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat(backend): chats on a project, each round a hidden task`.

### Task 2: Chat rounds stay off the board, out of counts and search

**Files:**
- Modify (one `on_board()` condition each):
  - `tasks/service.py` (`list_tasks`, `_column_tasks`, subtask counts in `tasks_out`, `_links_for`)
  - `projects/service.py` (`column_task_counts`, `move_column_tasks`: keep moving hidden rows too, no filter)
  - `projects/lifecycle.py` (`active_workflow_tasks`: keep, so closing a project pauses chats too, no filter)
  - `dashboard/scope.py` (add `on_board()` to a new `Scope.board_tasks()`, used by `tasks.py`'s `task_numbers`,
    `my_tasks`, `projects` and `finished_daily`, and by `workflows.py`'s `stages`, and by `activity.py`)
  - `sprints/service.py` (`points`, `complete`)
  - `search/documents.py` (`_task` returns `None` for `in_chat`; `ids_of` filters `on_board()`)
  - `mcp_server/server.py` (served by `list_tasks`)
  - `kb/service.py` (`refresh_links`: links to a hidden round are kept, since the round's page redirects to the chat)
- Test: `backend/tests/chats/test_hidden.py`

**Interfaces:** consumes `on_board()` and `start_chat` (Task 1).

- [ ] **Step 1: Write the failing tests.** Each starts one chat, then asserts:

```python
async def test_board_backlog_and_sprints_skip_chat_rounds(client, db)        # list_tasks with sprint="backlog"/no filter
async def test_column_counts_skip_chat_rounds(client, db)                     # columns[*].task_count unchanged
async def test_dashboard_numbers_skip_chat_rounds(client, db)                 # open_tasks, workflows_in_progress, stages unchanged
async def test_search_never_indexes_a_chat_round(db)                          # documents._task(round) is None
async def test_mcp_list_tasks_skips_chat_rounds(client, db)
async def test_a_chat_rounds_activity_is_not_in_recent_activity(client, db)
```

- [ ] **Step 2: Run** `uv run pytest tests/chats/test_hidden.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the filters above.
- [ ] **Step 4: Run** `uv run pytest tests/chats tests/tasks tests/dashboard tests/sprints tests/search tests/mcp tests/projects -q`.
  Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat(backend): chat rounds stay off the board, counts and search`.

### Task 3: The workflow, chat-aware

**Files:**
- Modify:
  - `workflow/documents.py` (`_start_build`)
  - `workflow/engine.py` (`wait_for`, plus a notification on `workflow.finished` for chats in `finish.finish_workflow`)
  - `workflow/instructions.py` (`framed_messages` across a chat's rounds)
  - `chats/service.py` (`chat_link`)
- Test: `backend/tests/chats/test_chat_workflow.py`

**Interfaces — Produces:**
- `def chat_link(chat_id) -> str` returns `/chats/{chat_id}`.
- `_start_build` skips creating step subtasks when `task.in_chat`; the steps keep `subtask_id: None`.
- `wait_for` notifies, for an `in_chat` task, the agent's owner **and the chat's starter**, with `link=chat_link(...)`.
  For other tasks it is unchanged.
- `finish_workflow` sends `Kind.needs_you` to the same people for an `in_chat` round, with the title
  `"Chat finished: {title}"` and `link=chat_link`.
- `instructions.framed_messages(db, task, states)` selects messages of **every task with the same `chat_id`** when the
  task is in a chat (otherwise only the task's own). The result is that `kept_in_mind` covers earlier rounds.
- The workflow's `chat.last_activity_at` is bumped in `record_workflow_event` for tasks with a `chat_id`.

- [ ] **Step 1: Write the failing tests:**

```python
async def test_approving_a_chat_plan_creates_no_subtasks(client, db)     # documents.decide approve → no Task with parent_id=round.id
async def test_waiting_chat_notifies_starter_and_owner_with_chat_link(client, client_factory, db)
    # a manager starts a chat with a member's agent; wait_for(question) → both get needs_you, link == f"/chats/{id}"
async def test_finishing_a_chat_round_notifies(client, db)              # title "Chat finished: Fix the empty email crash"
async def test_instructions_from_round_1_are_kept_in_round_2(client, db)  # delivered message on round 1 in build_prompt(round 2)
async def test_approved_chat_design_is_filed_in_the_knowledge_base(client, db)  # filing still runs for in_chat
async def test_chat_content_feeds_memory(client, db)  # creating a round and a chat message queue memory extraction
```

- [ ] **Step 2: Run** `uv run pytest tests/chats/test_chat_workflow.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the changes above.
- [ ] **Step 4: Run** `uv run pytest tests/chats tests/workflow -q`. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat(backend): chat rounds skip step cards and notify with the chat`.

### Task 4: A typed message does what the chat is waiting for

**Files:**
- Modify: `chats/service.py`, `chats/router.py`, `chats/schemas.py`
- Test: `backend/tests/chats/test_messages.py`

**Interfaces — Produces:**
- `Intent = Literal["answer","changes","tell","restart","new_round","closed"]`.
- `async def intent(db, chat, round_task, wf) -> Intent`, in this order:
  1. the chat is ended → `closed`;
  2. `wf.status == finished` → `new_round`;
  3. `needs == question` → `answer`;
  4. `needs` is design_approval or plan_approval → `changes`;
  5. an active run (queued or running) → `tell`;
  6. `needs` is escalation or human_code_review → `tell`;
  7. `wf.status == running` with no active run → `restart`;
  8. otherwise `tell`.
- `ChatOut.intent: Intent` (for the viewer; `closed` when they can't act).
- `POST /api/chats/{id}/messages` takes `MessageIn{body: 1..8000}` and returns `MessageOut{intent, round_key}`, 201.
  Under `engine.lock_task(round)`, it recomputes `intent` and runs it:
  - `answer` → `questions.answer(db, user, round, wf.open_question_id, None, body)`;
  - `changes` → `documents.decide(db, user, round, kind, latest_submitted_version, approve=False, comment=body)`;
  - `tell` → `create_comment(db, user, key, body, to_agent=True)`, then after the commit `steer_after_commit`;
  - `restart` → `engine.hand_to_agent(db, wf, round, ROLE_OF[stage], resume_kind="nudge", payload={"text": body}, requested_by=user.id)`;
  - `new_round` → Task 5's `start_next_round`;
  - `closed` → 409 `chat_ended`.
  It sets `chat.last_activity_at`. Errors from those functions pass through (409 `already_decided`, 403).

- [ ] **Step 1: Write the failing tests.** Drive the round into each state the way `tests/workflow/test_engine.py`
  does (`_ask`, `_submit`, `_finish` helpers).

```python
async def test_message_answers_the_open_question(...)        # intent "answer"; question answered with text == body; brainstorm resumes
async def test_message_while_plan_waits_asks_for_changes(...)  # plan v1 rejected with comment == body; a plan run queued
async def test_message_while_working_tells_the_agent(...)    # a comment with to_agent state "waiting"/"sending"
async def test_message_after_finish_starts_round_2(...)      # rounds length 2, round 2 stage brainstorm
async def test_message_follows_the_state_at_send_time(...)   # GET says "tell"; plan submitted before POST → POST does "changes"
async def test_second_reply_to_a_decided_plan_is_409(...)    # two "changes" posts for the same version → second 409 already_decided
async def test_message_to_an_ended_chat_is_409(...)          # 409 "chat_ended"
async def test_member_who_cannot_act_cannot_message(...)     # 403
```

- [ ] **Step 2: Run** `uv run pytest tests/chats/test_messages.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the changes above.
- [ ] **Step 4: Run** `uv run pytest tests/chats -q`. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat(backend): a chat message answers, asks for changes, tells or starts a round`.

### Task 5: Rounds

**Files:**
- Create: `backend/app/chats/context.py`
- Modify: `chats/service.py`, `workflow/context.py` (register the provider)
- Test: `backend/tests/chats/test_rounds.py`

**Interfaces — Produces:**
- `async def start_next_round(db, user, chat, message: str) -> Task`. The previous round's workflow must be finished
  (otherwise 409 `round_not_finished`). `branch_from` is the previous round's `wf.branch` when
  `prev.finish_outcome == "pr_opened"` and its pull request is not merged (`wf.pull_request` state is not `merged`);
  otherwise it is `None`. It then calls `create_round(..., branch_from=...)`.
- `async def earlier_rounds(db, task, role) -> str | None` is registered in `context.context_providers` and returns
  `None` unless the task is a chat round with `chat_round > 1`. Otherwise it returns a section headed
  `"## Earlier rounds of this chat"` with one block per earlier round:
  - `Round {n}: ` followed by the request, using `wrap_untrusted("round_request", description_md)`;
  - the approved plan's step titles (escaped, not wrapped: a person approved them);
  - the outcome line: `merged` / `pull request {pr_url}` / `branch {branch} kept` / `ended before finishing`.

  The section is cut to 8,000 characters, dropping the oldest round first. It ends with the line `If this request has nothing to do with the earlier rounds, say so in your first reply and suggest starting a new chat.`

- [ ] **Step 1: Write the failing tests:**

```python
async def test_next_round_branches_from_an_open_pr(...)      # prev pr_opened, PR open → round 2 branch_from == prev branch
async def test_next_round_after_a_merge_starts_from_default(...)  # branch_from is None
async def test_next_round_needs_the_previous_one_finished(...)    # 409 round_not_finished
async def test_round_2_prompt_has_the_earlier_rounds(...)    # "## Earlier rounds of this chat" with round 1's request and outcome
```

- [ ] **Step 2: Run** `uv run pytest tests/chats/test_rounds.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the changes above.
- [ ] **Step 4: Run** `uv run pytest tests/chats tests/workflow/test_context.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat(backend): chats go round again with what came before`.

### Task 6: Ending a chat, and adding a round to the board

**Files:**
- Modify: `chats/service.py`, `chats/router.py`, `chats/schemas.py`
- Test: `backend/tests/chats/test_end_and_board.py`

**Interfaces — Produces:**
- `POST /api/chats/{id}/end` (WF-6):
  - if the latest round's workflow is `running`, or `waiting_human` with needs other than `human_code_review`, it calls
    `engine.pause(db, user, round)`;
  - a round in `human_code_review` keeps waiting, so the pull request stays tracked;
  - it sets `status=ended` and `ended_at`, and returns `ChatOut`.
- `GET /api/chats/{id}/rounds/{n}/board` returns `BoardDefaults{title, description_md, column_id}`:
  - the title is the round's title;
  - the description is plain text: `{request}\n\n**Outcome:** {outcome}\n\nFrom the chat: /chats/{id}`. The outcome
    uses the same wording as Task 5, plus `in code review ({pr_url})` and `ended before finishing`;
  - the column is the first `done` column when finished, the first `review` column when `needs == human_code_review`
    or the stage is review (falling back to `before` if there is none), and the first `before` column otherwise.
- `POST /api/chats/{id}/rounds/{n}/board` takes `BoardIn{add: bool, title?, description_md?, column_id?}` (WF-6, 409
  `already_decided` when `chat_board` is set).
  - With `add=false` it sets `chat_board="declined"`.
  - With `add=true` it:
    1. sets `in_chat=False`, the title and description, the column (with `apply_column` and `end_position`) and
       `chat_board="added"`;
    2. creates the step subtasks from the approved plan's steps, in the done column for steps below `current_step`
       (all of them when finished) and the first before column for the rest, writing their ids into
       `doc.steps[i]["subtask_id"]`;
    3. publishes `task.created` for each.
  - Only a round whose workflow finished, or a round of an ended chat, can be decided; otherwise 409
    `round_not_finished`.

- [ ] **Step 1: Write the failing tests:**

```python
async def test_ending_a_working_chat_pauses_its_round(...)        # wf.status paused; chat status ended
async def test_ending_in_human_review_keeps_tracking(...)         # wf stays waiting_human / human_code_review
async def test_board_defaults_for_a_finished_round(...)           # column is done; description has "**Outcome:**" and "/chats/"
async def test_round_in_human_review_goes_to_the_review_column(...)
async def test_adding_to_the_board_shows_it_with_its_steps(...)   # list_tasks has it; 2 subtasks, step 1 done, step 2 before
async def test_declining_keeps_it_hidden(...)                     # chat_board == "declined"; not on the board
async def test_board_decision_is_once(...)                        # second POST → 409 already_decided
```

- [ ] **Step 2: Run** `uv run pytest tests/chats/test_end_and_board.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the changes above.
- [ ] **Step 4: Run** the whole backend suite into the workspace and read its tail. Expected: all pass. Never run two
  pytest runs at once.
- [ ] **Step 5: Commit** with the message `feat(backend): end a chat; add a round to the board`.

### Task 7: Chats page, project tab, list and new chat

**Files:**
- Create:
  - `frontend/src/lib/chats.ts`
  - `frontend/src/components/chats/{ChatList,NewChatDialog,ChatsPage}.tsx`
  - `frontend/src/app/(app)/chats/page.tsx`
  - `frontend/src/app/(app)/chats/[id]/page.tsx`
  - `frontend/src/app/(app)/projects/[key]/chats/page.tsx`
- Modify:
  - `frontend/src/components/shell/Sidebar.tsx` (a "Chats" item after Projects, with a count badge of chats waiting on
    the viewer)
  - `frontend/src/app/(app)/projects/[key]/layout.tsx` (a "Chats" tab after Board)
  - `frontend/src/components/task/TaskView.tsx` (redirect for `chat_id`)
  - `frontend/src/lib/api-types.ts` (`npm run gen:api`)
- Test: `frontend/src/components/chats/__tests__/ChatList.test.tsx`, `NewChatDialog.test.tsx`

**Interfaces — Produces:**
- `useChats(projectKey?: string)` and `useChat(id)` (query keys `qk.chats(project)` and `qk.chat(id)`).
- `stateText(state: ChatState, chat: Chat): string`, with this exact copy:
  - talking → `talking`
  - question → `waiting: answer the agent's question`
  - design_approval → `waiting: approve the design`
  - plan_approval → `waiting: approve the plan`
  - building → `building step {current} of {total}`
  - in_review → `in review`
  - human_code_review → `in code review · PR #{n}` (or `in code review` without a number)
  - escalation → `waiting: decide the escalation`
  - offline → `offline — starts when {owner}'s runner connects`
  - finished → `finished · PR #{n}` / `finished · merged` / `finished`
  - ended → `ended`
- `ChatsPage({ projectKey?: string })`:
  - a list on the left (`ChatList`) and the selected chat on the right (Task 8's `ChatView`); `/chats/[id]` selects
    one;
  - on a phone (below `md`) the list and the chat are separate screens;
  - the sidebar page has a project filter, `All projects ▾`.
- `NewChatDialog({ projectKey?: string })` has these fields:
  - **Project** (a select, preset and locked on the project tab);
  - **Agent** (`Any free agent` or a specific one, from `useProjectAgents` filtered to the ones the person may use);
  - **Message** (a textarea, required).

  Submitting posts `/api/chats` and goes to `/chats/{id}`.
- In `TaskView`, a task with `chat_id` replaces the view with a redirect to `/chats/{chat_id}`.

- [ ] **Step 1: Write the failing tests:** state copy for each state; the list puts waiting ones first as the API
  returns them and shows the project key on the sidebar page only; the dialog requires a message, presets and locks the
  project on the tab, and posts `{project_key, agent_id: null, message}` for "Any free agent"; TaskView redirects
  (`redirects a chat round's task page to the chat`).
- [ ] **Step 2: Run** `npx vitest run src/components/chats`. Expected: FAIL.
- [ ] **Step 3: Implement** the changes above.
- [ ] **Step 4: Run** `npx vitest run && npx tsc --noEmit -p . && npx eslint src`. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat(frontend): chats page, project tab and new chat`.

### Task 8: The chat view

**Files:**
- Create: `frontend/src/components/chats/{ChatView,ChatComposer,BoardDialog,RoundDivider,ChatProgress}.tsx`
- Modify: `frontend/src/lib/chats.ts`
- Test: `frontend/src/components/chats/__tests__/ChatView.test.tsx`, `ChatComposer.test.tsx`, `BoardDialog.test.tsx`

**Interfaces — Produces:**
- `ChatView({ chatId })`.
  - **Header:** the title, a project chip, an agent chip (`name · program`), `ChatProgress` (Talk · Design · Plan ·
    Build · Finish for the latest round), and `End chat` (when `can_act` and open; with a confirm when a run is
    active: "Stop the agent and end this chat? Whatever it committed stays on its branch.").
  - **Thread:** for each round, a `RoundDivider` (`Round {n} · {title}`, plus `from {branch_from}` when set, with
    **Change** as an inline input saving `PATCH /api/tasks/{key} {branch_from}` while the branch isn't locked), then
    that round's `ActivityThread` items (reusing the task components: QuestionCard, DocumentView for design and plan,
    the step rows).
  - **Composer:** `ChatComposer` at the bottom, sticky like the task composer.
- `ChatComposer({ chat })` shows a textarea and Send. The line under it comes from `intentText(chat.intent, agentName)`,
  with this exact copy:
  - answer → `Your message answers {agent}'s question.`
  - changes → `Your message asks {agent} to change the {design|plan}. Approve stays on the card.`
  - tell → `{agent} reads this straight away, without stopping.` while a run is active, otherwise
    `{agent} gets this when its next run starts.`
  - restart → `Your message starts {agent} again.`
  - new_round → `Starts a new round: the agent talks it through, then design, plan, build and finish again.`
  - closed → the composer is replaced by `This chat has ended.`

  It posts `/api/chats/{id}/messages`.
- `BoardDialog({ chat, round })` opens when a round has `board == "pending"` and the viewer can act. It loads `GET …/board`
  and shows the editable title, description and column, with `No, just end it` (`add:false`) and `Create task`
  (`add:true`). The title is `Add this to the board?`.

- [ ] **Step 1: Write the failing tests:** composer copy per intent, and that it posts and clears; the board dialog
  opens for a pending round, posts the edited fields, and declines; End chat confirms only while a run is active; round
  dividers show `from …` when set.
- [ ] **Step 2: Run** `npx vitest run src/components/chats`. Expected: FAIL.
- [ ] **Step 3: Implement** the changes above.
- [ ] **Step 4: Run** `npx vitest run && npx tsc --noEmit -p .`. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat(frontend): the chat view`.

### Task 9: Dashboard

**Files:**
- Create: `backend/app/dashboard/chats.py`, `frontend/src/components/dashboard/ChatsCard.tsx`
- Modify:
  - `backend/app/dashboard/{router or service that assembles the payload}.py`, `needs.py`, `agents.py`, `tasks.py`
    (`finished_daily`), plus the schemas
  - `frontend/src/components/dashboard/{Dashboard,Kpis,NeedsYou,RunningNow,FinishedChart}.tsx`
- Test: `backend/tests/dashboard/test_chats_dashboard.py`, `frontend/src/components/dashboard/__tests__/ChatsCard.test.tsx`

**Interfaces — Produces:**
- Payload additions:
  - `numbers.open_chats` and `numbers.chats_waiting_on_you`;
  - `chats: list[ChatBrief{id, title, project_key, state, current_step, steps_total, pr_url}]` (open chats in scope, at
    most 6, by `last_activity_at` descending);
  - needs items gain `chat_id: UUID | None`;
  - running and queued items gain `chat_id`;
  - `finished_daily` items gain `chats: int`, counting rounds whose workflow finished that day (chats are no longer
    counted in agents/people).
- Scope rules: `mine` covers chats I started or whose agent I own; `team` and `all` follow the project scope.
- Frontend:
  - the Kpis tile `Open chats`, with `{n} waiting on you`;
  - `NeedsYou` and `RunningNow` rows with a `chat` tag that link to `/chats/{id}`;
  - `ChatsCard` (title `Chats`, links `New chat` and `All chats`, rows `{title} · {project}` with `stateText`);
  - `FinishedChart` gets a third series (amber `chats`) and the title `Finished · last 14 days`.

- [ ] **Step 1: Write the failing tests:** numbers and lists include an open chat; mine-scope filtering; the finished
  series moves a finished round from agents to chats; ChatsCard renders the rows and links.
- [ ] **Step 2: Run** `uv run pytest tests/dashboard -q` and `npx vitest run src/components/dashboard`. Expected: FAIL.
- [ ] **Step 3: Implement** the changes above.
- [ ] **Step 4: Run** the same two commands. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat: chats on the dashboard`.

### Task 10: End to end

**Files:** create `frontend/e2e/chats.spec.ts` (project key CHT, set up like `e2e/tell-agent.spec.ts`).

- [ ] **Step 1: Write the spec.** The scenario:
  - brainstorm asks a question;
  - after the answer, `submit_design`;
  - plan `submit_plan` with 1 step;
  - implement `complete_step`;
  - step review approved;
  - final review approved;
  - finish `merge_local`. The prompt markers are the methodology headings, as in `mockups.spec.ts`.

  The flow:
  1. New chat from the project tab (preset project, Any free agent): "Fix the empty email crash".
  2. The chat shows the agent's question; typing a reply answers it (the composer line said so).
  3. Approve the design. Type "Split the plan into one step" while the plan waits: the plan is rejected with that text
     and resubmitted.
  4. Approve the plan; the build runs; the chat shows `finished · merged`; `Add this to the board?` appears.
     **Create task** puts it on the board in Done, with one Done subtask.
  5. Type a new message: `Round 2` appears, at the talking stage.
  6. **End chat**, then **No, just end it**. The composer shows `This chat has ended.`
  7. The dashboard shows the `Open chats` tile and the Chats card (before ending), and the chat in Needs you while it
     waits.
- [ ] **Step 2: Run** the full e2e on a fresh `megoo-e2e` stack (the scratchpad `e2e-run.sh`). Expected: all pass.
- [ ] **Step 3: Commit** with the message `test(e2e): agent chats`.
