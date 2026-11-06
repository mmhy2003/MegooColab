# Freestyle Chats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A chat can be started in **Freestyle** mode: the agent does what each message asks, one turn at a time, with write access in the chat's worktree and no design, plan, reviews, finishing step or escalations.

**Architecture:** A freestyle chat is an ordinary chat whose single round runs one new run role, `freestyle` (workspace policy, resumable session). The engine treats a freestyle turn's end as "wait for the next message" (`Needs.reply`) instead of advancing stages. The chat service maps messages to new turns, finishes the round on End chat, and shows new states. The runner is untouched.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (backend), Next.js + React Query + Vitest (frontend), Playwright (e2e).

**Spec:** `docs/superpowers/specs/2026-11-06-freestyle-chats-design.md` — read it; it is the authority.

## Global Constraints

- Workflow chats, board tasks and every existing run role behave exactly as today (spec anti-goal).
- No runner change (`runner/` untouched).
- `chats.mode`: String(10), not null, server default `workflow`; values `workflow` | `freestyle`.
- New enum values: `RunRole.freestyle = "freestyle"`, `Needs.reply = "reply"`, `Kind.agent_replied = "agent_replied"`; new chat states `working`, `reply`; new chat intent `turn`.
- Methodology key `freestyle`, group `chats` (`OTHER_KEYS["chats"] = ["freestyle"]`), default text `backend/app/workflow/methodology_texts/defaults/freestyle.md`.
- Copy (verbatim):
  - Dialog label: **How should the agent work?**
  - Workflow: "Talks it through, writes a design and a plan for you to approve, builds it step by step with reviews, then finishes as the project is set up to."
  - Freestyle: "Does what you ask, one reply at a time, with no design, plan or reviews. It can change files, switch branches, commit and push when you ask."
  - States: `working` → "working"; `reply` → "waiting for your reply".
  - Composer line for `turn`: "<agent> starts working on your message."
  - Freestyle message framing: "The person you are working with sent you this. Do what it asks."
  - Notification title: "<agent> replied in <chat title>"; preference label: "My agent replied in a freestyle chat".
  - Header chip: "Freestyle".
- Conversation-so-far section: heading `## Conversation so far`, within 12,000 characters, newest kept, agent replies wrapped as untrusted.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No Prettier. Never run two pytest runs at once. Migrations are generated only with `cd backend && DEV_DATABASE_URL=postgresql+asyncpg://megoo:megoo@localhost:5433/megoo_migrate bash scripts/makemigration.sh "<message>"` (never another database).

## Review Focus

1. A message sent while a freestyle turn is still **queued** (agent offline) — expected: it is taken by that turn at its start, and the chat does not end up "waiting for your reply" with the message unread. (Task 2 test `test_message_left_waiting_starts_the_next_turn`.)
2. A freestyle turn that **fails three times in a row** — expected: each time the chat waits for a reply; no escalation, no automatic retry. (Task 2 test `test_failed_turns_never_retry_or_escalate`.)
3. **End chat while a turn is running** — expected: the run is cancelled and the round is finished (not paused), so "Add this to the board?" defaults to Done. (Task 4 test `test_ending_a_freestyle_chat_finishes_its_round_even_mid_turn`.)
4. A **workflow** chat after this change — expected: still pauses on End chat, still starts brainstorm, messages still map to answer/changes/tell/restart/retry/new_round. (Task 4 test `test_workflow_chats_are_unchanged`.)
5. An agent program that **cannot resume** sessions — expected: every turn's prompt carries the conversation so far, including the agent's own previous replies. (Task 3 test `test_fresh_freestyle_prompt_has_the_conversation_so_far`.)

---

## File Structure

- `backend/app/chats/models.py` — `ChatMode` enum, `Chat.mode`.
- `backend/migrations/versions/<rev>_chat_mode.py` — the column.
- `backend/app/workflow/models.py` — `RunRole.freestyle`, `Needs.reply`.
- `backend/app/notifications/models.py` — `Kind.agent_replied` (+ default prefs).
- `backend/app/workflow/methodology.py`, `methodology_texts/defaults/freestyle.md` — the text.
- `backend/app/workflow/engine.py` — role tables, `start_freestyle`, freestyle turn-end and failure paths.
- `backend/app/workflow/freestyle.py` (new) — the freestyle turn-end handler, `queue_turn`, the conversation-so-far section.
- `backend/app/workflow/instructions.py`, `backend/app/agent_runs/service.py`, `backend/app/workflow/context.py` — freestyle wording, no re-sent messages on resume, conversation section.
- `backend/app/mcp_server/workflow_tools.py`, `kb_tools.py` — tool permissions.
- `backend/app/chats/schemas.py`, `service.py` — mode, intent `turn`, states, End chat.
- `backend/app/dashboard/needs.py`, `backend/app/tasks/router.py` — leave `Needs.reply` out of Needs you.
- Frontend: `lib/api-types.ts` (regenerated), `lib/chats.ts`, `lib/workflow.ts`, `lib/notifications.ts`, `components/chats/NewChatDialog.tsx`, `ChatView.tsx`, `ChatList.tsx`, `components/dashboard/ChatsCard.tsx`, `components/board/TaskCard.tsx`, `components/workflow/StageTrack.tsx`, `components/workflow/MethodologyEditor.tsx`.
- `frontend/e2e/freestyle.spec.ts` (new).

---

### Task 1: Data, roles and the freestyle text

**Files:**
- Modify: `backend/app/chats/models.py`, `backend/app/workflow/models.py`, `backend/app/notifications/models.py`, `backend/app/workflow/methodology.py`, `backend/app/workflow/engine.py:67-117` (role tables only), `backend/app/workflow/context.py:35-46`, `backend/app/mcp_server/workflow_tools.py:58-92`, `backend/app/mcp_server/kb_tools.py:30-36`
- Create: `backend/app/workflow/methodology_texts/defaults/freestyle.md`, migration `backend/migrations/versions/<rev>_chat_mode.py`
- Test: `backend/tests/workflow/test_freestyle_setup.py`

**Interfaces:**
- Produces:
  - `class ChatMode(StrEnum): workflow = "workflow"; freestyle = "freestyle"` in `app.chats.models`; `Chat.mode: Mapped[ChatMode] = mapped_column(String(10), default=ChatMode.workflow, server_default="workflow")`.
  - `RunRole.freestyle`; `Needs.reply`; `Kind.agent_replied` with `DEFAULT_PREFS[Kind.agent_replied] == (True, False, False, False)`.
  - `ROLE_POLICY[RunRole.freestyle] == RunPolicy.workspace`; `RunRole.freestyle` not in `FRESH_ROLES` nor `R1_ROLES`; `session_key(RunRole.freestyle, None) == "freestyle"`; `ROLE_KEY[RunRole.freestyle] == "freestyle"`.
  - `TOOL_ROLES`: `freestyle` added to `ask_human`'s set (the line-63 set), `record_decision`, `record_tests`; `KB_TOOL_ROLES["kb_write"]` gains `freestyle`. `ROLE_HINT`-style dict at `workflow_tools.py:81-92` gains `RunRole.freestyle: "Do what the latest message asks, then reply and end your turn."`
  - `methodology.OTHER_KEYS["chats"] == ["freestyle"]`.

- [ ] **Step 1: Write the failing tests** in `backend/tests/workflow/test_freestyle_setup.py`:

```python
from app.chats.models import Chat, ChatMode
from app.mcp_server.kb_tools import KB_TOOL_ROLES
from app.mcp_server.workflow_tools import TOOL_ROLES
from app.notifications.models import DEFAULT_PREFS, Kind
from app.workflow import engine, methodology
from app.workflow.context import ROLE_KEY
from app.workflow.models import Needs, RunPolicy, RunRole


def test_freestyle_role_writes_and_resumes():
    assert engine.ROLE_POLICY[RunRole.freestyle] == RunPolicy.workspace
    assert RunRole.freestyle not in engine.FRESH_ROLES and RunRole.freestyle not in engine.R1_ROLES
    assert engine.session_key(RunRole.freestyle, None) == "freestyle"
    assert ROLE_KEY[RunRole.freestyle] == "freestyle"


def test_freestyle_tools():
    for tool in ("ask_human", "record_decision", "record_tests"):
        assert RunRole.freestyle in TOOL_ROLES[tool]
    for tool in ("submit_design", "submit_plan", "complete_step", "submit_review", "report_finish",
                 "report_pr_fix", "submit_pr_review", "show_mockup"):
        assert RunRole.freestyle not in TOOL_ROLES[tool]
    assert RunRole.freestyle in KB_TOOL_ROLES["kb_write"]


def test_new_values_and_defaults():
    assert Needs.reply == "reply" and Kind.agent_replied == "agent_replied"
    assert DEFAULT_PREFS[Kind.agent_replied] == (True, False, False, False)
    assert methodology.OTHER_KEYS["chats"] == ["freestyle"] and "freestyle" in methodology.ALL_KEYS


async def test_freestyle_text_is_seeded(db):
    await methodology.seed_defaults(db)
    text = (await methodology.current(db, "freestyle")).body_md
    assert "megoo/" in text and "ask_human" in text and ".megoocolab/" in text


async def test_a_chat_is_a_workflow_chat_unless_told(db, client):
    from tests.chats.helpers import start, world
    await world(client, db)
    chat = await start(client)
    row = await db.get(Chat, __import__("uuid").UUID(chat["id"]))
    assert row.mode == ChatMode.workflow
```

- [ ] **Step 2: Run them, expect failures** — `cd backend && uv run pytest -q -p no:cacheprovider tests/workflow/test_freestyle_setup.py` → ImportError / AttributeError on `ChatMode`, `RunRole.freestyle`.

- [ ] **Step 3: Implement** the values and tables listed under Produces. Write `freestyle.md` (heading `# Freestyle: do what the person asks, one turn at a time`), covering every point of the spec's "The turn run" bullet list (direct conversation; worktree starts on `megoo/<KEY>-…`; may create/switch branches, commit, merge, push, open pull requests with the developer's own git credentials, never tokens in URLs or printed credentials; switch back to its own branch before ending a turn if it checked out another; never check out a branch checked out elsewhere; nothing is reviewed — say what changed, which branch, what's left; `ask_human` only when it truly cannot proceed; never edit `.megoocolab/`). Generate the migration with the command in Global Constraints (message "chat mode"), then check it adds only `chats.mode` with `server_default='workflow'` (hand-edit if autogenerate adds anything else).

- [ ] **Step 4: Run** the same command → all pass. Then `uv run pytest -q -p no:cacheprovider tests/workflow/test_methodology.py tests/mcp_server` (or the folder holding MCP tool tests) → pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app backend/migrations backend/tests/workflow/test_freestyle_setup.py
git commit -m "feat(workflow): freestyle run role, chat mode and the freestyle text"
```

---

### Task 2: The freestyle turn in the engine

**Files:**
- Create: `backend/app/workflow/freestyle.py`
- Modify: `backend/app/workflow/engine.py` (`start_freestyle`; `_on_run_finished` failure path; `on_run_finished` engine_error path)
- Test: `backend/tests/workflow/test_freestyle_engine.py`

**Interfaces:**
- Consumes: Task 1 values.
- Produces:
  - `async def start_freestyle(db, user, task) -> TaskWorkflow` in `engine`: same checks as `engine.start` (type, `_usable_agent`, not active/paused/finished); sets `driver=runner`, `stage=Stage.build`, `enforcement=Enforcement.unenforced`, `needs=None`, `current_step=None`, `failures=0`, `nudged=False`, `escalation_reason=None`, clears `sessions`, `started_at`; records `workflow.started`; enqueues `RunRole.freestyle`.
  - `async def queue_turn(db, wf, task, *, requested_by) -> AgentRun` in `app.workflow.freestyle`: `engine.enqueue(db, wf, task, RunRole.freestyle, requested_by=requested_by)` (no resume text: the message rides as a waiting comment).
  - `async def handle_turn_end(db, wf, task, run) -> None` registered as `engine.ROLE_HANDLERS[RunRole.freestyle]`:
    1. an open question asked by this run → `engine.wait_for(db, wf, Needs.question)`;
    2. an undelivered answer → `questions.deliver(...)` (as `_handle_brainstorm_or_plan`);
    3. a comment to the agent with `delivery == Delivery.waiting` on this task → `queue_turn(...)`;
    4. else `engine.wait_for(db, wf, Needs.reply, notify=False)` and notify `Kind.agent_replied` to the chat's starter only (`chat_people(db, task)[0][0]`), title `f"{agent.name} replied in {chat.title}"`, body = first 500 chars of `run.summary or ""`, link = chat link, `task_id`, `project_id`.
  - `async def wait_after_failure(db, wf, task, run) -> None` in `app.workflow.freestyle`: `engine.wait_for(db, wf, Needs.reply, notify=False)`; no notification; `wf.failures` untouched.
  - In `engine._on_run_finished`: when `role == RunRole.freestyle` and the run failed or was cancelled by nobody (`run.status in (failed, cancelled)` and not the person-cancel / owner-deactivated branches above it) → `await freestyle.wait_after_failure(...)` and return, before the `wf.failures += 1` block.
  - In `engine.on_run_finished`'s `except` branch: when the run's role is `freestyle` and `wf.status == running` → `wait_for(db, wf, Needs.reply, notify=False)` instead of `escalate(..., "engine_error")`.

Test setup for this task (in the test file): reuse `tests.chats.helpers.world/start`; until Task 4 lands, start the round by creating the chat normally and then calling `engine.start_freestyle` is not possible on an active workflow — so **this task's tests call `start_freestyle` on a fresh board task**: create a task assigned to `w.agent["id"]` via `POST /api/projects/PAY/tasks`, then in a `SessionLocal()` call `engine.start_freestyle(s, w.owner, task)` and commit. End runs with a helper:

```python
async def _end(run_id, status="completed", summary=None):
    async with SessionLocal() as s:
        run = await s.get(AgentRun, run_id)
        await engine.lock_workflow(s, run.task_id)
        run.status, run.summary = status, summary
        await engine.on_run_finished(s, run)
        await s.commit()
```

- [ ] **Step 1: Write the failing tests** in `backend/tests/workflow/test_freestyle_engine.py`:
  - `test_start_freestyle_queues_one_writing_turn`: after start → workflow `(driver, stage, enforcement, status) == ("runner", "build", "unenforced", "running")`; exactly one active run with `workflow_role == "freestyle"` and `policy == "workspace"`; no `brainstorm` run.
  - `test_completed_turn_waits_for_a_reply_and_notifies_once`: `_end(run, "completed", "Done: bumped VERSION")` → `(wf.status, wf.needs) == ("waiting_human", "reply")`; exactly one `Notification` with `kind == "agent_replied"` for the owner (the task's agent owner stands in for the chat starter on a board task: assert the handler falls back to the agent's owner when the task is not in a chat); no `needs_you` notification.
  - `test_failed_turns_never_retry_or_escalate`: three times — `_end(run, "failed")` → `(status, needs, escalation_reason) == ("waiting_human", "reply", None)`, no new queued run, `wf.failures == 0`; between ends, queue the next turn with `freestyle.queue_turn` (as Task 4's message will).
  - `test_message_left_waiting_starts_the_next_turn`: add a `Comment(task_id, author_user_id=owner, body_md="also tag it", to_agent_id=agent, delivery=Delivery.waiting)`; `_end(run, "completed")` → a new queued `freestyle` run and `wf.status == "running"`. Then `_end(new_run, "failed")` with another waiting comment present → no new run, `needs == "reply"`.
  - `test_question_in_a_turn_waits_for_the_answer`: insert an open `WorkflowQuestion` for the run (as `tests/workflow/test_engine.py::_ask` does) → after `_end` `needs == "question"`.
  - `test_engine_error_in_a_freestyle_turn_waits_for_a_reply`: monkeypatch `engine.ROLE_HANDLERS[RunRole.freestyle]` to raise → after `_end`, `needs == "reply"` and no `workflow.escalated` event.

- [ ] **Step 2: Run** `uv run pytest -q -p no:cacheprovider tests/workflow/test_freestyle_engine.py` → fail (`start_freestyle` missing).

- [ ] **Step 3: Implement** the Produces items. For the notification recipient on a task not in a chat (only in this task's tests), use the agent's owner; in a chat use `chat_people(db, task)` and take the starter (`chat.started_by`).

- [ ] **Step 4: Run** the file → pass; then `uv run pytest -q -p no:cacheprovider tests/workflow/test_engine.py tests/workflow/test_questions.py` → pass (workflow roles unchanged).

- [ ] **Step 5: Commit** — `git commit -m "feat(workflow): a freestyle turn waits for the next message, never retries or escalates"`

---

### Task 3: What a freestyle turn is told

**Files:**
- Modify: `backend/app/workflow/instructions.py` (`RULE`/`STEER_PREFIX` selection), `backend/app/agent_runs/service.py:377-387`, `backend/app/workflow/context.py` (`build_prompt`), `backend/app/workflow/freestyle.py`
- Test: `backend/tests/workflow/test_freestyle_prompt.py`

**Interfaces:**
- Consumes: Task 2's `start_freestyle`, `queue_turn`, `_end` helper pattern.
- Produces:
  - `FREESTYLE_RULE = "The person you are working with sent you this. Do what it asks."` and `FREESTYLE_STEER_PREFIX = "MegooColab: the person you are working with sent you this while you work. Do what it asks.\n\n"` in `instructions`; every place that writes `RULE` / `STEER_PREFIX` picks the freestyle one when the run's (or, for `kept_in_mind`/`take_waiting`, the target run's) `workflow_role == "freestyle"`. Add a `freestyle: bool = False` keyword where a function needs to know.
  - In `agent_runs/service.py`'s dispatch: `earlier = kept_in_mind(...)` only when resumed **and** the role is not `freestyle`.
  - `async def conversation_so_far(db, task) -> str | None` in `app.workflow.freestyle`: ordered by time, each comment addressed to the agent framed as `frame_instruction(...)`, and for each completed or failed freestyle run of the task with a non-empty `summary`, `"[reply by <agent name> at <YYYY-MM-DD HH:MM>]\n" + wrap_untrusted("agent_reply", summary)`; heading `## Conversation so far`; cut from the oldest to fit 12,000 characters; None when empty.
  - `build_prompt(..., role=RunRole.freestyle)`: appends `conversation_so_far` (instead of the "Instructions from people on this task" section) — only used when the run starts fresh; a resumed run gets just its new messages (dispatch already sends `resume_prompt` + new instructions).

- [ ] **Step 1: Write the failing tests** in `backend/tests/workflow/test_freestyle_prompt.py`:
  - `test_fresh_freestyle_prompt_has_the_conversation_so_far`: start freestyle; end turn 1 with `summary="Created release/2026.11.06.208"`; add a waiting comment "push it"; queue turn 2 with no stored session (clear `wf.sessions`); dispatch it through the same path the existing tests use (`tests/workflow/test_instructions_dispatch.py` shows how) → its prompt contains `"## Conversation so far"`, `"Created release/2026.11.06.208"` and `"push it"`, in that order.
  - `test_resumed_freestyle_turn_is_not_resent_earlier_messages`: same, but `wf.sessions["freestyle"] = "s1"` before turn 2, and a first delivered message "first ask" → the dispatched `resume_prompt` contains "push it" and not "first ask".
  - `test_freestyle_messages_use_freestyle_wording`: the dispatched text contains `"The person you are working with sent you this. Do what it asks."` and not `"approved design or plan"`.
  - `test_workflow_messages_keep_their_wording`: a workflow (brainstorm) run's new instructions still contain `"approved design or plan"`.

- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** the Produces items.
- [ ] **Step 4: Run** the file → pass; then `uv run pytest -q -p no:cacheprovider tests/workflow/test_instructions.py tests/workflow/test_instructions_dispatch.py tests/workflow/test_context.py` → pass.
- [ ] **Step 5: Commit** — `git commit -m "feat(workflow): a freestyle turn gets the conversation so far, in its own words"`

---

### Task 4: Freestyle chats in the chat service

**Files:**
- Modify: `backend/app/chats/schemas.py`, `backend/app/chats/service.py`, `backend/app/dashboard/needs.py:47`, `backend/app/tasks/router.py:51-53`
- Test: `backend/tests/chats/test_freestyle.py`

**Interfaces:**
- Consumes: `ChatMode`, `start_freestyle`, `queue_turn`, `Needs.reply`.
- Produces:
  - `ChatIn.mode: Literal["workflow", "freestyle"] = "workflow"`; `ChatOut.mode: Literal["workflow", "freestyle"]`.
  - `ChatState` gains `"working"`, `"reply"`; `Intent` gains `"turn"`.
  - `create_round` calls `engine.start_freestyle` when `chat.mode == freestyle`.
  - `chat_state`: freestyle chat → `ended`/`finished` as today; `needs == question` → `question`; `needs == reply` → `reply`; `run_queued and not agent_online` → `offline`; else `working`. `NEEDS_STATE[Needs.reply] = "reply"`.
  - `intent` for a freestyle chat: ended/no task → `closed`; `needs == question` → `answer`; active run → `tell`; paused → `restart`; `needs == reply` → `turn`; otherwise `tell`. Never `new_round`, `changes`, `retry`.
  - `send_message` `turn` branch: `create_comment(db, user, key, body, to_agent=True, image_ids=images)` then `freestyle.queue_turn(db, wf, task, requested_by=user.id)`.
  - `end_chat`: for a freestyle chat, cancel an active run (as `engine.pause` does, by this user) and finish the round: `wf.stage = Stage.done` then `finish.finish_workflow(db, wf, task, user.id)` (wf in any non-finished state).
  - Needs you: `dashboard/needs.py` and `tasks/router.py` `needs_you` also exclude `Needs.reply` (keep `merge_confirmation` excluded). The chats waiting count stays as is (its explicit list doesn't include `reply`).

- [ ] **Step 1: Write the failing tests** in `backend/tests/chats/test_freestyle.py` (use `world`, `start(client, mode="freestyle")`, `_round`, and the `_end` helper from Task 2):
  - `test_starting_a_freestyle_chat_runs_a_freestyle_turn`: response `mode == "freestyle"`, `state == "working"`, `intent == "tell"`; one active run, role `freestyle`.
  - `test_a_reply_starts_the_next_turn_with_the_message`: `_end(run, "completed", "Done")` → chat `state == "reply"`, `intent == "turn"`; POST message "push it" → 201, `intent == "turn"`; a new queued freestyle run; the comment `"push it"` exists with `delivery == "waiting"`; still exactly one round.
  - `test_a_freestyle_chat_waiting_for_a_reply_is_not_needs_you`: after `_end(... "completed")` → `/api/dashboard` needs has no item for the chat; `/api/chats/count` → `{"waiting": 0}`; `/api/projects/PAY/tasks?needs_you=true` (whatever the router's path is) has no round.
  - `test_a_freestyle_question_is_needs_you`: an open question → chat `state == "question"`, `/api/chats/count` → `{"waiting": 1}`.
  - `test_ending_a_freestyle_chat_finishes_its_round_even_mid_turn`: while the run is queued, POST end → 200; the run is cancelled; workflow `status == "finished"`, `stage == "done"`; the round's `board == "pending"` and the board dialog defaults (`GET /api/chats/{id}/rounds/1/board-defaults` or the existing defaults endpoint) suggest the done column.
  - `test_workflow_chats_are_unchanged`: `start(client)` → `mode == "workflow"`, first run role `brainstorm`; ending it while running pauses it (`status == "paused"`).

- [ ] **Step 2: Run** `uv run pytest -q -p no:cacheprovider tests/chats/test_freestyle.py` → fail.
- [ ] **Step 3: Implement** the Produces items.
- [ ] **Step 4: Run** `uv run pytest -q -p no:cacheprovider tests/chats tests/dashboard tests/workflow` → pass.
- [ ] **Step 5: Commit** — `git commit -m "feat(chats): start a chat in freestyle mode; each message is a turn"`

---

### Task 5: The freestyle chat on screen

**Files:**
- Modify: `frontend/src/lib/api-types.ts` (regenerate: `cd frontend && npm run gen:api`), `frontend/src/lib/chats.ts`, `frontend/src/lib/workflow.ts`, `frontend/src/lib/notifications.ts`, `frontend/src/components/chats/NewChatDialog.tsx`, `frontend/src/components/chats/ChatView.tsx`, `frontend/src/components/chats/ChatList.tsx`, `frontend/src/components/dashboard/ChatsCard.tsx` (only if it needs the chip), `frontend/src/components/board/TaskCard.tsx:69`, `frontend/src/components/workflow/StageTrack.tsx:26-34`, `frontend/src/components/workflow/MethodologyEditor.tsx:18-31`
- Test: `frontend/src/components/chats/__tests__/NewChatDialog.test.tsx` (create or extend), `ChatView.test.tsx`, `ChatList.test.tsx`, `frontend/src/components/workflow/__tests__/StageTrack.test.tsx`, `frontend/src/components/board/__tests__/TaskCard.test.tsx`

**Interfaces:**
- Consumes: the API from Task 4 (`mode`, states `working`/`reply`, intent `turn`, `Needs.reply`, `Kind.agent_replied`).
- Produces:
  - `chatStateText`: `working` → "working", `reply` → "waiting for your reply".
  - `intentText`: `turn` → `` `${agent} starts working on your message.` ``.
  - `NEEDS_TEXT.reply = "Waiting for your reply"`; `KIND_LABELS.agent_replied = "My agent replied in a freestyle chat"`.
  - `MethodologyEditor`: `METHODOLOGY_STAGES` gains `"chats"`; card `{ id: "chats", label: "Chats", keys: ["freestyle"] }`.
  - TaskCard: no NEEDS YOU for `needs === "reply"` (as for `merge_confirmation`); StageTrack: `reply` is not a pink waiting stop.

- [ ] **Step 1: Write the failing tests:**
  - NewChatDialog: shows the label "How should the agent work?" with radios "Workflow" (checked by default) and "Freestyle" and their two descriptions verbatim; choosing Freestyle and sending posts `mode: "freestyle"`; reopening the dialog has Freestyle checked (localStorage key `megoo.newChatMode`); with `localStorage` throwing, it still renders with Workflow.
  - ChatView: a freestyle chat (`mode: "freestyle"`, `state: "reply"`, `intent: "turn"`) shows a "Freestyle" chip and no `list` named "Progress"; the header text "waiting for your reply"; the composer line "laptop-claude starts working on your message."; a workflow chat still shows the progress list.
  - ChatList: a freestyle chat's row shows the "Freestyle" chip and "working" / "waiting for your reply".
  - TaskCard: `needs: "reply"` shows no "NEEDS YOU"; StageTrack: `needs: "reply"` isn't marked waiting.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/components/chats src/components/board src/components/workflow` → the new tests fail.
- [ ] **Step 3: Implement** the Produces items and the dialog (radios in a `fieldset` with `legend` "How should the agent work?"; remember the choice in `localStorage` under `megoo.newChatMode`, read/write in try/catch).
- [ ] **Step 4: Run** `npx vitest run` → all pass; `npx tsc --noEmit` and `npx eslint` → clean.
- [ ] **Step 5: Commit** — `git commit -m "feat(chats): choose Workflow or Freestyle when starting a chat"`

---

### Task 6: End to end

**Files:**
- Create: `frontend/e2e/freestyle.spec.ts`
- Test: itself

**Interfaces:**
- Consumes: everything above; `frontend/e2e/helpers/runner.ts` (`buildBinaries`, `startRunner`, `onPrompt`, `say`, `mintLinkedRunnerToken`) as `frontend/e2e/chats.spec.ts` uses them.

- [ ] **Step 1: Write the test** "a freestyle chat: two turns, then End chat" modelled on `chats.spec.ts`'s setup (project with key `FRE`, a git repo, a linked runner with the fake agent). Scenario: on `# Freestyle` prompts — turn 1 (`onPrompt("(first turn marker)")` or the first message text) writes `notes.txt`, commits, and `say("Created notes.txt on megoo/FRE-1")`; turn 2 (prompt contains "rename it") renames the file, commits and says "Renamed to NOTES.md". Steps: open New chat, choose **Freestyle**, send "Add a notes file"; expect the header chip "Freestyle", then "waiting for your reply" and the agent's reply; send "rename it"; expect "Renamed to NOTES.md" and "waiting for your reply"; the repository's `megoo/FRE-1-*` branch has both commits (`git log`); End chat → confirm → "Add this to the board?" shows Column **Done**; "No, just end it"; "This chat has ended."
- [ ] **Step 2: Run** on a fresh stack (`docker compose -p megoo-e2e -f deploy/docker-compose.yml -f deploy/docker-compose.build.yml --env-file .superpowers/e2e.env up -d --build --wait`, stopping `megoocolab-dev-caddy-1` first and starting it after) with `cd frontend && npx playwright test e2e/freestyle.spec.ts e2e/chats.spec.ts --reporter=line` → 2 passed.
- [ ] **Step 3: Commit** — `git commit -m "test(e2e): a freestyle chat runs two turns and ends"`
