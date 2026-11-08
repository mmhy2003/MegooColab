# Agents Ask Other Projects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A task's or chat's agent asks other projects about their code on its own, waits when it can't go on, and picks up again by itself when the answers arrive.

**Architecture:**
- **Prompt:** the existing A2A plumbing gains a new prompt section (`app/a2a/context.py`).
- **Tool:** two new `ask_project` parameters, `wait` and `follow_up_to`.
- **Waiting and resuming:** a new module, `app/a2a/waits.py`, owns the "waiting on another project" state:
  - a hook in `engine._on_run_finished`, before the role handlers, holds a run that ended waiting;
  - a pass in the A2A routing loop, woken right after an answer commits, resumes the agent through `engine.hand_to_agent`;
  - a new resume kind, `project_answers`.
- **UI:** shows the wait, offers "Go on without it", "Answer it yourself" and "Withdraw", and groups follow-ups. It is built only after the owner approves a mockup.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (backend/), MCP server (app/mcp_server), Next.js + React Query + Vitest (frontend/), Playwright e2e with the Go fake agent.

**Spec:** `docs/superpowers/specs/2026-11-08-ask-other-projects-design.md` (approved; commit e71ac61)

## Global Constraints

- **Branch:** `feat/ask-other-projects`, off `develop`. Never commit to `develop` or `main`. Commit subjects follow `type(area): sentence` (see AGENTS.md).
- **Migrations:**
  - generate and try them only against `megoo_migrate` (AGENTS.md, Checks);
  - give every new FK an explicit name;
  - downgrade, then upgrade, on `megoo_migrate`.
- **One pytest run at a time.** Run the backend tests from `backend/` with `uv run pytest <paths>`. Frontend: `npx tsc --noEmit`, `npx eslint <files>`, `npx vitest run <files>`. No Prettier.
- **Untrusted text:**
  - project names and descriptions, question text, answers and earlier questions go into prompts escaped (`_escape`) or wrapped (`wrap_untrusted`), as in `app/a2a/context.py` today;
  - no secret ever goes into a prompt (answers are already scrubbed).
- **Limits:**
  - `QUESTION_LIMIT = 20` questions per task, or per chat (all rounds together), counting every status;
  - a project list of at most `MAX_LISTED = 30` projects, each description cut to `DESCRIPTION_CHARS = 150`;
  - the slow-answer notification default is 30 minutes, settable from 5 to 1440 (`project_answer_notify_minutes`).
- **Refusal codes:** `invalid_follow_up` and `question_limit` (MCP `ToolError` text, and 422 / 429 in the service).
- **Exact copy** (from the spec):
  - the prompt section of Task 4;
  - the resume texts of Task 6;
  - the notifications of Task 7: "SLW-Q3 is waiting for a person at SLW to answer." and "SLW hasn't answered SLW-Q3 yet.";
  - the UI labels of Task 9.
- **Scope:** runner-driven workflows only. Connect-only and manual drivers are untouched.
- **UI tasks (9) start only after the owner approves the mockup** (Task 8). That's the controller's job, not the implementer's.

## Review Focus

1. **A run that both completed its work and asked with `wait`** (for example, `complete_step` with passing tests). It must move on normally and not hold. `produced_outcome` must catch it. Test: `test_completed_step_with_wait_question_is_not_held` (Task 5).
2. **The answer commits while the asking run is still running.** The run's end must resume at once with the answer, never hold with nothing pending, and never nudge. Test: `test_answered_before_run_end_resumes_at_once` (Task 5).
3. **Two answers commit at the same moment.** The agent resumes exactly once: `resume_settled` takes the engine's locks and re-checks under them. Test: `test_two_settled_passes_resume_once` (Task 6).
4. **A project whose key is also a common word** ("API", "WEB"), or a 2-letter key. The mention mark must not fire on lowercase prose: keys match whole-word and case-sensitive only. Test: `test_lowercase_word_does_not_mark_key` (Task 4).
5. **A person who can act on the task, but didn't ask, withdraws the agent's question.** This is allowed. Someone who can only read the task gets 403. Test: `test_task_actor_may_withdraw_agent_question` (Task 6).

---

### Task 1: Data — columns, the new wait, quiet waits

**Files:**
- Modify: `backend/app/a2a/models.py` (class `Question`)
- Modify: `backend/app/org/models.py` (class `OrgSettings`)
- Modify: `backend/app/workflow/models.py` (`Needs`, new `QUIET_NEEDS`)
- Modify: `backend/app/dashboard/needs.py:48`, `backend/app/tasks/router.py:53` (use `QUIET_NEEDS`)
- Create: `backend/migrations/versions/<rev>_ask_other_projects.py` (down_revision `06a5e01d6e28`)
- Test: `backend/tests/a2a/test_models.py`, `backend/tests/workflow/test_needs_you.py`

**Interfaces:**
- Produces:
  - **`Question`:**
    - `follow_up_of_id: Mapped[uuid.UUID | None]`, FK `a2a_questions.id`, `ON DELETE SET NULL`, constraint name `a2a_questions_follow_up_of_id_fkey`;
    - `wait: Mapped[bool]`, default False, server_default false;
    - `delivered_at: Mapped[datetime | None]`;
    - `asker_human_notified_at: Mapped[datetime | None]`;
    - `asker_slow_notified_at: Mapped[datetime | None]`.
  - **`OrgSettings.project_answer_notify_minutes: Mapped[int]`**, default 30, server_default "30".
  - **`Needs.project_answer = "project_answer"`.**
  - **`QUIET_NEEDS = frozenset({Needs.merge_confirmation, Needs.reply, Needs.project_answer})`**: waits that ask nobody.

- [ ] **Step 1: Write the failing tests**

```python
# tests/a2a/test_models.py
async def test_question_wait_and_follow_up_columns(db):
    q1 = await _question(db)            # existing helper in this file, or build one like test_ask._ask
    q2 = await _question(db, follow_up_of_id=q1.id, wait=True)
    assert q2.follow_up_of_id == q1.id and q2.wait is True
    assert q1.wait is False and q1.delivered_at is None
    await db.delete(q1); await db.flush(); await db.refresh(q2)
    assert q2.follow_up_of_id is None   # SET NULL

# tests/workflow/test_needs_you.py
async def test_project_answer_wait_is_not_needs_you(client, db):
    # a workflow waiting_human with needs=project_answer: not in GET /api/dashboard needs, not in the task list's needs flag
    ...assert the task key is absent from the Needs-you list and needs_count is 0
```

- [ ] **Step 2: Run them, and see them fail:** `uv run pytest tests/a2a/test_models.py tests/workflow/test_needs_you.py -k "wait_and_follow_up or project_answer"`. Expected: FAIL (unknown column, or the task shown in Needs you).
- [ ] **Step 3: Add the columns, `Needs.project_answer` and `QUIET_NEEDS`.** Replace the two `not_in((Needs.merge_confirmation, Needs.reply))` call sites with `QUIET_NEEDS`. Also replace any other place that leaves out both `merge_confirmation` and `reply` (`grep -rn "Needs.reply" app`), such as the dashboard's waiting counts. Then then write the migration as in AGENTS.md (on `megoo_migrate`: generate, then downgrade and upgrade). `needs` is `String(30)`, so the new value needs no enum change.
- [ ] **Step 4: Run the Step 2 tests, plus `tests/a2a tests/workflow/test_needs_you.py tests/dashboard`.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(questions): store waits, follow-ups and delivery on questions`

### Task 2: Asking — `wait`, `follow_up_to`, limits

**Files:**
- Modify: `backend/app/a2a/service.py` (`ask`), `backend/app/a2a/access.py` (`open_question_count`)
- Modify: `backend/app/mcp_server/a2a_tools.py` (`ask_project`)
- Test: `backend/tests/a2a/test_ask.py`, `backend/tests/mcp/test_a2a_tools.py`

**Interfaces:**
- Consumes: the Task 1 columns.
- Produces:
  - **`service.ask(..., wait: bool = False, follow_up_to: str | None = None)`**, with the other parameters unchanged.
  - **`service.QUESTION_LIMIT = 20`.**
  - **`service.task_question_count(db, task: Task) -> int`:** counts the task's questions, or all of its chat's tasks' (`Task.chat_id`) for a chat round, in every status.
  - **`service.parse_ref(ref: str) -> tuple[str, int]`:** turns `"SLW-Q3"` into `("SLW", 3)`. Refuses with 422 `invalid_follow_up`.
  - **`service.follow_up_chain(db, q: Question) -> list[Question]`:** the earlier questions, oldest first, following `follow_up_of_id`, at most 10.
  - **The `question_asked` event data** gains `follow_up_of_number: int | None`.

Rules:
- **`follow_up_to`** must name a question of the same target project whose `from_task_id` is the task, or one of its chat's tasks. Otherwise 422 `invalid_follow_up`.
- **The follow-up's preferred agent:** the follow-up gets `prefer_agent_id` = the earlier question's `answered_by_agent_id`, when that agent is still in `project_agents`, with `prefer_only=False`.
- **The per-task limit:** an agent's ask (`agent_id` set and a task) over the limit gets 429 `question_limit`. People asking by hand aren't limited.
- **The per-user cap:** questions an agent asks for a task (`asked_by_agent_id` set and `from_task_id` set) are skipped by the cap check, and left out of `open_question_count`.
- **MCP:** `ask_project(project_key, question, context=None, task_key=None, wait=False, follow_up_to=None)` maps `HTTPException` codes to `ToolError` text as the other tools do. The docstring says: "wait=True: you can't go on without this answer; end your turn and you'll be started again with it. follow_up_to: the ref of an earlier question this one follows (e.g. SLW-Q3)."

- [ ] **Step 1: Write the failing tests**

```python
async def test_ask_stores_wait_and_follow_up(...):        # q2 = ask(..., follow_up_to=ref(q1), wait=True)
    assert q2.wait and q2.follow_up_of_id == q1.id
async def test_follow_up_prefers_previous_answering_agent(...):
    assert q2.prefer_agent_id == q1.answered_by_agent_id and q2.prefer_only is False
async def test_follow_up_refused_for_other_task_or_project_or_unknown(...):  # 3 cases -> 422 invalid_follow_up
async def test_follow_up_across_chat_rounds_allowed(...)
async def test_agent_ask_limit_twenty_per_chat(...):     # 20 asks over two rounds OK, the 21st -> 429 question_limit
async def test_person_asking_by_hand_not_limited_per_task(...)
async def test_agent_questions_skip_per_user_cap(...):   # 20 open agent questions; a person still asks; agent asks pass
async def test_ask_project_tool_passes_wait_and_follow_up(...)   # tests/mcp/test_a2a_tools.py
async def test_ask_project_tool_reports_question_limit(...)      # ToolError("question_limit")
```

- [ ] **Step 2: Run them, and see them fail:** `uv run pytest tests/a2a/test_ask.py tests/mcp/test_a2a_tools.py`. Expected: FAIL (unexpected keyword `wait`).
- [ ] **Step 3: Implement the rules above** in `ask`, `open_question_count` and `ask_project`.
- [ ] **Step 4: Run `tests/a2a tests/mcp/test_a2a_tools.py`.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(questions): agents ask with wait and follow-ups, within a per-task limit`

### Task 3: Answering follow-ups with the earlier thread

**Files:**
- Modify: `backend/app/a2a/prompts.py`, `backend/app/a2a/routing.py:137`, `backend/app/a2a/schemas.py` (`QuestionOut`), `backend/app/a2a/service.py` (`question_out`)
- Test: `backend/tests/a2a/test_routing.py`, `backend/tests/a2a/test_answer.py`

**Interfaces:**
- Consumes: `service.follow_up_chain` (Task 2).
- Produces:
  - **`prompts.answer_prompt(q: Question, target_key: str, earlier: list[Question] = ()) -> str`.**
  - **`QuestionOut.follow_up_of: FollowUpRef | None`**, where `FollowUpRef(BaseModel): id: uuid.UUID; ref: str`.

- **The answering prompt with `earlier`:** it adds `## Earlier questions in this thread`. Each earlier question shows its ref, title, body and answer with citations, inside `wrap_untrusted("earlier", …)`, within `EARLIER_CHARS = 8000`, newest kept whole. `ANSWER_PROMPT` gains the rule: "- If earlier questions in this thread are shown, build on their answers instead of repeating them."
- **Routing:** `route_question` passes `earlier=await service.follow_up_chain(db, q)`.

- [ ] **Step 1: Write the failing tests**
  - `test_follow_up_answer_prompt_carries_earlier_thread`: the routed run's `prompt` contains "## Earlier questions in this thread", q1's ref and its answer text, and the earlier text inside an `<untrusted` wrapper.
  - `test_question_out_names_follow_up`: `GET /api/questions/{q2}` returns `follow_up_of.ref == "QBB-Q1"`.
- [ ] **Step 2: Run them, and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `tests/a2a`.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(questions): a follow-up is answered with the earlier questions in view`

### Task 4: The prompt section and the resume tail

**Files:**
- Modify: `backend/app/a2a/context.py`
- Modify: `backend/app/workflow/context.py` (new `resume_providers` list, next to `context_providers`)
- Modify: `backend/app/workflow/engine.py` (`enqueue`: append the resume tail when a session is resumed)
- Test: `backend/tests/a2a/test_context.py` (create if absent), `backend/tests/workflow/test_context.py`

**Interfaces:**
- Consumes: `task_question_count`, `QUESTION_LIMIT` (Task 2).
- Produces:
  - **`a2a.context.projects_context(db, task, role) -> str | None`**, registered in `context_providers`.
  - **`a2a.context.resume_tail(db, task, role) -> str | None`**, registered in `workflow.context.resume_providers: list[ContextProvider]`.
  - **`a2a.context.mentioned_keys(projects: list[Project], texts: list[str]) -> set[str]`**, a pure function.
  - **Delivery stamping:** `a2a_context` and `resume_tail` set `Question.delivered_at` on every answer they include.

**`projects_context`:**
- **The text:** the spec's block, verbatim, from the heading "## Other projects you can ask" to the last line. It's left out for `RunRole.finish`, and when no project is listed.
- **The projects:** `accessible_project_ids(owner)` (the `_owner` of `kb/context.py`), minus the task's project, minus `ProjectStatus.archived`.
- **Each line:** `- {KEY} — {name}: {description[:150]}`, escaped and on one line. Mentioned projects come first, each with `   ← mentioned in this task` (or `in this chat` when `task.in_chat`). After `MAX_LISTED = 30` projects, it adds `(N more: ask by key if you know it)`.
- **The "left" line:** `You can ask up to 20 questions for this task; N are left.` At zero: `You've used all 20 questions for this task: carry on with what you have, or ask the person.`
- **Mentions** (`mentioned_keys`):
  - a key matches as a whole word, case-sensitive (`\bKEY\b`);
  - a name matches case-insensitively, as a whole phrase;
  - the texts are the task's title and description, plus, for `task.in_chat`, the `body_md` of the task's comments that have `to_agent_id` set.

**`resume_tail`:**
- **Order:** answers to this task's questions with `status == answered` and `delivered_at is None`, in the `a2a_context` format; then a 2-line reminder, "You can ask other projects with ask_project (wait=True when you can't go on without the answer)."; then the "left" line.
- **When:** in `enqueue`, when `session` is set, the tail is appended to `text` with a blank line between them. If `text` is empty, the tail becomes the text.

- [ ] **Step 1: Write the failing tests**
  - `test_lists_accessible_projects_except_own_and_archived`
  - `test_marks_and_orders_mentioned_projects`
  - `test_lowercase_word_does_not_mark_key`: key `API`, text "call the api" → not marked; "call API" → marked.
  - `test_chat_messages_count_as_mentions`
  - `test_escapes_project_name_and_description`
  - `test_absent_for_finish_and_without_other_projects`
  - `test_left_line_counts_and_runs_out`
  - `test_resume_tail_carries_undelivered_answers_once`: the second enqueue's tail has no answer.
  - `test_fresh_prompt_answers_stamp_delivered`
- [ ] **Step 2: Run them, and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `tests/a2a tests/workflow/test_context.py tests/workflow/test_freestyle_prompt.py`.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(questions): agents are told which projects they can ask, and when`

### Task 5: Waiting — hold a run that ended waiting

**Files:**
- Create: `backend/app/a2a/waits.py`
- Modify: `backend/app/workflow/engine.py` (`_on_run_finished`, just before `handler = ROLE_HANDLERS.get(role)`; and `_pending_need`)
- Test: `backend/tests/a2a/test_waits.py`

**Interfaces:**
- Consumes: the Task 1 columns, and `engine.wait_for`, `engine.latest_run`, `questions.has_open_question`.
- Produces:
  - **`waits.open_waits(db, task_id) -> list[Question]`:** `wait` is true, the status is in `OPEN_STATUSES`, and `from_task_id == task_id`.
  - **`waits.produced_outcome(db, run) -> bool`:** true when the run has one of:
    - an open `WorkflowQuestion` (`has_open_question`);
    - a `WorkflowDocument` with `submitted_run_id == run.id` and status `submitted`;
    - a `StepReview` for the run;
    - a non-empty `run.step_result`.
  - **`waits.hold_after_run(db, wf, task, run) -> bool`:** called by the engine before the role handler; true means the run's end is handled.
    - **No hold:** false for `RunRole.finish`, or when `produced_outcome`.
    - **Hold:** if `open_waits`, then `wait_for(db, wf, Needs.project_answer, notify=False)` and true.
    - **Otherwise** false. Task 6 adds the "resume at once" branch.
  - **`_pending_need`** returns `Needs.project_answer` when `open_waits` is non-empty. It's checked after the `WorkflowQuestion` check.

- [ ] **Step 1: Write the failing tests**
  - `test_brainstorm_ending_with_open_wait_question_waits_quietly`: needs `project_answer`, not nudged, no `needs_you` notification.
  - `test_freestyle_turn_with_open_wait_waits_and_queues_no_turn`: a waiting comment exists; still no run is queued.
  - `test_implement_with_wait_question_is_not_step_incomplete`
  - `test_completed_step_with_wait_question_is_not_held` (Review Focus 1)
  - `test_ask_human_question_takes_precedence`: needs `question`, and after it's answered and the next run ends, needs `project_answer`.
  - `test_questions_without_wait_never_hold`
  - `test_failed_run_does_not_hold`
  - `test_resumed_paused_workflow_returns_to_project_answer`
  - `test_message_while_waiting_is_tell_and_starts_nothing`: the chat intent is `tell`.
- [ ] **Step 2: Run them, and see them fail:** `uv run pytest tests/a2a/test_waits.py`.
- [ ] **Step 3: Implement `waits.py`, and hook it into the engine** with a local import (`from app.a2a import waits`; a2a imports the engine).
- [ ] **Step 4: Run `tests/a2a tests/workflow tests/chats`.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(questions): a run that can't go on without an answer waits for it`

### Task 6: Resuming — answers, "Go on without it", withdraw

**Files:**
- Modify: `backend/app/a2a/waits.py`, `backend/app/a2a/service.py` (`on_answered`, `withdraw`, `question_out.can_withdraw`), `backend/app/a2a/access.py`, `backend/app/a2a/routing.py` (loop pass and wake), `backend/app/a2a/router.py`
- Modify: `backend/app/workflow/context.py` (`resume_text` kind `project_answers`), `backend/app/workflow/engine.py` (`RESUME_HEADING["project_answers"] = "Answers from other projects"`)
- Test: `backend/tests/a2a/test_waits.py`, `backend/tests/a2a/test_answer.py`

**Interfaces:**
- Consumes: Task 5.
- Produces:
  - **`waits.settle(db, wf, task, *, requested_by: uuid.UUID, gave_up: Sequence[Question] = ()) -> AgentRun | None`:**
    - payload `{"answers": [{ref, title, answer_md, citations}], "unanswered": [ref, …]}`;
    - the answers are the task's `wait` questions that are answered and undelivered;
    - the unanswered are those withdrawn and undelivered, plus `gave_up`;
    - it stamps `delivered_at` on all of them;
    - it calls `engine.hand_to_agent(db, wf, task, role, step=…, resume_kind="project_answers", payload=…, requested_by=…, resume_session_ref=…)`, where the role and step come from `engine.latest_run`, and `resume_session_ref` is that run's `session_ref` when the role is in `engine.FRESH_ROLES`, else None.
  - **`waits.resume_settled() -> int`:** its own session. For each `TaskWorkflow` with `status == waiting_human` and `needs == project_answer`:
    - `engine.lock_task` first, re-checking the state under the lock;
    - if `open_waits` is empty, call `settle`;
    - commit, then `engine.dispatch_queued`;
    - return the number resumed.
  - **`waits.wake_after_commit(db) -> None`:** registers a one-shot SQLAlchemy `after_commit` listener on `db.sync_session` that calls `routing.wake()`.
  - **`routing.wake() -> None`**, with `route_loop` waiting on stop or wake. `route_and_dispatch` calls `await waits.resume_settled()`.
  - **`access.can_act_on_task(db, user, task) -> bool`:** `engine.can_act` or `engine.manages`, without raising.
  - **`POST /api/tasks/{key}/project-waits/go-on`** → `WorkflowOut`:
    - `require_actor`, then 409 `not_waiting` unless the needs is `project_answer`;
    - clears `wait` on the open waits;
    - calls `settle(..., gave_up=those)`.
- **Resume text** for `project_answers`, using `_bounded` like `answer`:
  - the header "Answers from other projects arrived.";
  - for each answer, `### {ref}: {title}`, then `wrap_untrusted("answer", answer + Sources)`;
  - for each unanswered ref: "{ref} wasn't answered. Carry on with what you have, say plainly which assumptions you made, and ask the person if you can't decide."
- **Hooks:**
  - **`hold_after_run` gains "resume at once":** when nothing is open but the task has `wait` questions that are settled and undelivered, it calls `await settle(db, wf, task, requested_by=owner)` and returns true.
  - **`on_answered`:** if `q.from_task_id` and `q.wait`, call `wake_after_commit(db)`. Never resume inside it (lock order).
  - **`withdraw`:** allowed for the asker, an admin, or `can_act_on_task` on `q.from_task_id`. It calls `wake_after_commit`.
  - **`question_out.can_withdraw`** uses the same rule.

- [ ] **Step 1: Write the failing tests**
  - `test_answered_before_run_end_resumes_at_once` (Review Focus 2): a `project_answers` run is queued with the answer in `resume_prompt`, and there is no nudge.
  - `test_last_answer_resumes_same_session_with_answers`: the run's `workflow_role` and `step` are the asking run's, `resume_session_ref` is the stored session, and `resume_prompt` contains "Answers from other projects arrived." and the answer.
  - `test_two_questions_resume_once_after_second_answer`
  - `test_two_settled_passes_resume_once` (Review Focus 3): call `resume_settled()` twice concurrently → one queued run.
  - `test_go_on_without_it_resumes_with_unanswered_line_and_late_answer_never_resumes`: the later answer appears in the next prompt's "Answers from other projects", and no extra run is queued.
  - `test_withdraw_last_wait_resumes`
  - `test_task_actor_may_withdraw_agent_question` (Review Focus 5): a manager → 200; a viewer of the project → 403.
  - `test_freestyle_chat_resumes_as_a_turn_with_waiting_message`: the queued run is `freestyle`. At its start the person's message sent while waiting is handed over (`delivery` becomes delivered).
  - `test_go_on_refused_when_not_waiting` → 409 `not_waiting`
  - `test_on_answered_wakes_routing_after_commit`: monkeypatch `routing.wake`; it's called only after the commit.
- [ ] **Step 2: Run them, and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `tests/a2a tests/workflow tests/chats tests/mcp`.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(questions): the agent picks up again when the answers it waits for arrive`

### Task 7: Notifications and the setting

**Files:**
- Modify: `backend/app/a2a/waits.py`, `backend/app/a2a/routing.py` (after `notify_waiting` at `needs_human`; the loop pass), `backend/app/org/router.py` (`AdminSettingsIn`/`Out`: `questions: QuestionSettings | None`, where `QuestionSettings(BaseModel): notify_after_minutes: int = Field(ge=5, le=1440)`)
- Test: `backend/tests/a2a/test_waits.py`, `backend/tests/org/` (the settings test file)

**Interfaces:**
- Produces:
  - **`waits.notify_asker(db, q: Question, kind: Literal["human", "slow"]) -> None`:**
    - only for `q.wait` and `q.from_task_id`;
    - once per kind, using `asker_human_notified_at` / `asker_slow_notified_at`;
    - `Kind.question_waiting`, sent to the recipients `engine.wait_for` would pick (the agent's owner and the task's assignee, or `chat_people` for a chat), with the same link;
    - titles: `"{ref} is waiting for a person at {KEY} to answer."` / `"{KEY} hasn't answered {ref} yet."`, and `body=q.title`.
  - **`waits.notify_slow() -> int`:** in the loop pass. It covers open `wait` questions whose `created_at` is older than `org.project_answer_notify_minutes`, with `asker_slow_notified_at` null.

- [ ] **Step 1: Write the failing tests**
  - `test_needs_human_tells_asker_once`
  - `test_slow_answer_tells_asker_after_setting_minutes_once`: set the minutes to 5 and backdate `created_at` by 6 minutes; a second pass sends nothing.
  - `test_question_without_wait_tells_asker_nothing`
  - `test_admin_sets_notify_minutes_bounds`: 4 → 422; 30 → stored; GET returns it.
- [ ] **Step 2: Run them, and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `tests/a2a tests/org tests/notifications`.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(questions): tell the person when another project's answer is slow`

### Task 8: API for the UI, and the mockup gate

**Files:**
- Modify: `backend/app/workflow/schemas.py` (`WorkflowOut.project_waits: list[ProjectWaitOut]`), `backend/app/workflow/router.py`
- Modify: `backend/app/chats/schemas.py` (`ChatState` gains `"waiting_answer"`; `ChatOut.waiting_on: list[str] = []`), `backend/app/chats/service.py` (`NEEDS_STATE[Needs.project_answer] = "waiting_answer"`; `waiting_on` = refs of the latest round's `open_waits`)
- Modify: `frontend/src/lib/api-types.ts` (`npm run gen:api`)
- Test: `backend/tests/workflow/test_engine.py` (or the router test), `backend/tests/chats/`

**Interfaces:**
- Produces: `ProjectWaitOut(BaseModel): question_id: uuid.UUID; ref: str; project_key: str; title: str; status: str; can_answer: bool; can_withdraw: bool`. It's filled from `open_waits` for the viewer (`can_answer_question`, the Task 6 withdraw rule).

- [ ] **Step 1: Write the failing tests**
  - `test_workflow_out_lists_project_waits_with_viewer_rights`
  - `test_chat_out_state_waiting_answer_and_refs`
- [ ] **Step 2: Run them, and see them fail.** Then **Step 3:** implement, and run `npm run gen:api`. **Step 4:** run `tests/workflow tests/chats`, then `npx tsc --noEmit` in `frontend/`.
- [ ] **Step 5: Commit.** `feat(questions): the workflow and chat say which answers they wait for`
- [ ] **Step 6 (controller, not the implementer): the mockup.** Make a mockup through the visual companion, following the earlier mockups in this session. It covers:
  - the waiting banner in a task's workflow panel and in a chat, with its three buttons;
  - the chat list row "waiting for SLW's answer", under Working;
  - follow-ups grouped in the Questions section;
  - the admin field.

  Stop until the owner approves it. Write any changes they ask for into Task 9 before dispatching it.

### Task 9: Frontend

**Files:**
- Modify: `frontend/src/lib/workflow.ts` (`NEEDS_TEXT.project_answer: "Waiting for another project's answer"`; export `QUIET_NEEDS`)
- Modify: `frontend/src/components/board/TaskCard.tsx:69` (use `QUIET_NEEDS`)
- Create: `frontend/src/components/questions/ProjectWaitBanner.tsx`
- Modify: `frontend/src/components/workflow/WorkflowPanel.tsx`, `frontend/src/components/chats/ChatView.tsx` (render the banner while waiting)
- Modify: `frontend/src/lib/chats.ts` (`waiting_answer` → group `working`; `stateText` → "waiting for SLW's answer", or "waiting for answers from SLW and PAY (2)", from `chat.waiting_on`), `frontend/src/components/chats/ChatList.tsx` (MARK/TONE for `waiting_answer`)
- Modify: `frontend/src/components/questions/TaskQuestions.tsx` (follow-ups indented under `follow_up_of`)
- Modify: `frontend/src/components/task/ActivityThread.tsx` (`question_asked` with `follow_up_of_number` → "asked SLW a follow-up to Q3 (Q4)")
- Modify: `frontend/src/app/(app)/admin/settings/page.tsx` (a "Questions to other projects" section: "Tell me when an answer takes longer than [30] minutes")
- Test: the `__tests__` next to each component

**Interfaces:**
- Consumes: `WorkflowOut.project_waits`, `ChatOut.waiting_on`, `QuestionOut.follow_up_of` (Task 8, generated types). `POST /api/tasks/{key}/project-waits/go-on`, `POST /api/questions/{id}/withdraw`.
- Produces: `ProjectWaitBanner({ taskKey, waits, canAct, onChanged })`.
  - **Title:** "Waiting for SLW's answer (SLW-Q3)" for one, or "Waiting for answers from SLW and PAY (2)".
  - **Buttons:**
    - "Go on without it", when `canAct`;
    - "Answer it yourself", a link to `/questions/{id}`, per wait with `can_answer`;
    - "Withdraw", per wait with `can_withdraw`.
  - **Behavior:** confirms before withdrawing, then invalidates the workflow, chat and task questions queries.

- [ ] **Step 1: Write the failing tests** (Vitest). Each asserts the exact copy above:
  - the banner's title for one wait and for two;
  - the buttons follow `canAct`, `can_answer` and `can_withdraw`;
  - "Go on without it" posts to the endpoint;
  - `chatGroup` puts `waiting_answer` under `working`, and `stateText` gives both forms;
  - the TaskCard shows no needs badge for `project_answer`;
  - TaskQuestions nests a follow-up under its first question;
  - the ActivityThread follow-up wording;
  - the admin field saves `questions.notify_after_minutes`.
- [ ] **Step 2: Run them, and see them fail:** `npx vitest run <files>`.
- [ ] **Step 3: Implement, matching the approved mockup.**
- [ ] **Step 4:** `npx tsc --noEmit`, `npx eslint <changed files>`, `npx vitest run`. Expected: all pass.
- [ ] **Step 5: Commit.** `feat(questions): show what a task waits for, and let people go on without it`

### Task 10: End to end

**Files:**
- Create: `frontend/e2e/ask-projects.spec.ts`. It follows `frontend/e2e/questions.spec.ts` and `frontend/e2e/freestyle.spec.ts` for setup, the fake agent, `onPrompt`, `mcp` and `say`.

**Scenario** (two projects, keys `ASK` and `ANS`; a freestyle chat on ASK; `ANS` has a repository and the admin's agent bound so it answers in auto mode):
1. **The chat's first message** names "ANS". The fake agent, on the freestyle prompt:
   - asserts nothing (the prompt is checked in step 6);
   - calls `mcp("ask_project", {project_key: "ANS", question: "How are orders webhooks signed?", wait: true})`;
   - says "Asked ANS; waiting".
2. **On `ANSWER_PROMPT`**, the fake agent calls `submit_answer` with a citation.
3. **The chat:**
   - shows "waiting for ANS's answer" in the list, and the banner with "Waiting for ANS's answer (ANS-Q1)";
   - after the answer, the agent resumes on its own. On the prompt "Answers from other projects arrived." the fake agent says "Using ANS's HMAC signing".
4. **The reply** "Using ANS's HMAC signing" appears in the chat without any new message from the person.
5. **A second message** makes the agent ask `ANS` with `wait: true` again, with the routing held (no free slot: `max_concurrent_runs` 0, or the answering scenario sleeps). The person clicks "Go on without it". The agent resumes on the prompt containing "wasn't answered" and says "Carrying on without it".
6. **The prompt:** the first run's prompt contains "## Other projects you can ask" and "ANS — " with "← mentioned in this chat". Read it with `GET /api/agent-runs?task=…`, or the existing helper that `questions.spec.ts` uses.

- [ ] **Step 1: Write the spec, and run it on a fresh stack** (AGENTS.md e2e routine): `npx playwright test e2e/ask-projects.spec.ts --reporter=line`. Expected: PASS. Run `e2e/questions.spec.ts e2e/freestyle.spec.ts e2e/workflow.spec.ts e2e/chats.spec.ts` too. Expected: PASS.
- [ ] **Step 2: Commit.** `test(e2e): a chat asks another project, waits, and picks up again`
