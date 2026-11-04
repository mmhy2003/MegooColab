# Knowledge Base: Write a Document with an Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person drafts a knowledge base document with one of their machine agents. The draft and a conversation
sit side by side. Each agent turn's changes are marked for keep or undo. The person can type in the draft too, and
saves it as a revision credited to them with the agent.

**Architecture:**
- **Backend:** a new `app/kb_drafts` package holds drafts, their conversation and the last turn's marks. A
  block diff of the agent's whole submitted text makes the marks.
- **Runs:** each request is an `AgentRun` targeting the draft (a third run target beside task and question,
  like A2A answering runs). It goes through the existing queue and dispatch. The agent reads and submits through
  two new MCP tools.
- **Runner:** it gains a `drafts/1` capability. A draft run works in a per-draft folder under the cache:
  - a detached worktree of the project's repository for project drafts;
  - an empty folder otherwise.

  The server's `draft_done` message, or a 30-day sweep, removes it.
- **Frontend:** a new writing page, a start dialog, **My drafts**, and a banner on documents.

**Tech Stack:** FastAPI, async SQLAlchemy, Alembic, MCP server (Python); Go runner; Next.js 16, React 19, TanStack
Query, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-04-kb-agent-writing-design.md`

## Global Constraints

- **Migrations:** generated only against `megoo_migrate`:
  `DATABASE_URL=postgresql+asyncpg://megoo:megoo@localhost:5433/megoo_migrate SECRET_KEY=throwaway uv run alembic revision --autogenerate -m "..."`.
- **pytest:** never two runs at once. The whole backend suite is `uv run pytest -q -n auto` (from `backend/`).
- **Frontend:** no Prettier. API types are regenerated with `npm run gen:api` (from `frontend/`) after backend
  schema changes.
- **Size limit:** body text uses the knowledge base limit, 500,000 characters (`app.kb.service.check_body`,
  `422 too_large`).
- **Agent choice:**
  - project space: agents with a usable binding for the project that `can_use_agent(db, user, agent, project)`
    allows;
  - team or organisation space: `Agent.owner_id == user.id` only.
- **Access:** only people who may write in the target space (`app.kb.access.can_write`) may start, request, edit or
  save; every call rechecks.
- **Privacy:** a draft is visible only to its person (`KbDraft.user_id`). Everyone else gets 404 `draft_not_found`.
- **Phones:** every new screen works at 280 px wide with no sideways scrolling. The writing page uses tabs
  **Draft** / **Conversation** below the `lg` breakpoint.
- **Copy (exact strings from the spec):**
  - "Write with an agent"
  - "Start drafting"
  - "Draft · not saved"
  - "Keep all" / "Undo all"
  - "Save to KB…"
  - "Discard draft"
  - "<agent> is writing…"
  - "Stop"
  - "Waiting for <agent> to come online"
  - "About: selected text in '<section>'" / "whole document"
  - "Keeps the N open changes"
  - "N changes not reviewed"
  - "Show what changed" / "Ask the agent to bring it in" / "Save over it anyway"
  - "You have an unsaved draft with <agent> · Open"
  - "My drafts"
  - "Written with <agent>"
  - "<agent> updated your draft '<title>'"
  - "No agent can work on this project" / "You have no agents"
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- No version bumps (those happen only on release).

## Decisions this plan makes beyond the spec

These go in the ledger as rulings when executed:

- **D1. No `RunRole` member.** Draft runs have `workflow_role = None` and are identified by `AgentRun.draft_id`, as
  answering runs are identified by `question_id`.
  - The spec's "new run role" is met by the methodology key `kb_draft` and its own Admin › Methodology tab
    ("Knowledge base").
  - Adding a `RunRole` would put draft runs into every workflow registry (`ROLE_POLICY`, `ROLE_HANDLERS`,
    `TOOL_ROLES`…) that assumes a task.
- **D2. Every draft run needs `drafts/1`, project drafts too.** The spec only required a new runner for team and
  organisation drafts.
  - An older runner would make project drafts a task-style worktree with a `megoo/…` branch in the person's
    repository, and nothing would ever remove it.
  - With `drafts/1`, project drafts get a detached worktree that `draft_done` removes.
- **D3. One session across turns** works like `ask_human`'s resume: the next run's `resume_session_ref` is the
  draft's last `session_ref`. The spec says "as chats do", but chats actually start a new task per round.
- **D4. Deletions cascade.** Deleting a document or space deletes its drafts (FK `ON DELETE CASCADE`) after their
  active runs are stopped. A deleted agent sets `KbDraft.agent_id` to NULL, and the person picks another agent on
  the writing page.

## Review Focus

1. **A submit after Stop or after a save/discard race:** `kb_draft_submit` from a run that is no longer running, or
   whose draft is gone, must change nothing. The run token is already dead after the run ends; the draft-gone
   case returns `draft_gone`. Pinned in Task 5.
2. **Fenced code blocks with blank lines:** a fence containing blank lines must stay one block. Otherwise a change
   inside it is marked as several blocks, and Undo reassembles a broken fence. Pinned in Task 2.
3. **Person's edit while a turn is queued but not started:** the run must read the edited text (it reads at run
   time through `kb_draft_read`, not at enqueue), and its marks diff against that text. Pinned in Task 5.
4. **Agent removed, or the person lost access mid-draft:**
   - an agent removed from the project, or deleted, refuses requests with 422 `agent_not_available`, and the page
     offers the agent picker;
   - lost write access gives 403 on every call.

   Pinned in Task 3.
5. **Runner offline at save or discard:** `draft_done` cannot be sent, so it is skipped silently, and the runner's
   30-day sweep removes the folder. Pinned in Task 7 (sweep) and Task 6 (no error when no connection).

---

### Task 1: Draft tables and the third run target

**Files:**
- Create: `backend/app/kb_drafts/__init__.py`, `backend/app/kb_drafts/models.py`
- Modify: `backend/app/agent_runs/models.py` (`draft_id` column, check constraint), `backend/app/models.py` (import
  the new models)
- Create: `backend/migrations/versions/<rev>_kb_drafts.py` (autogenerated, then hand-edit the constraint)
- Test: `backend/tests/kb_drafts/__init__.py`, `backend/tests/kb_drafts/test_models.py`

**Interfaces:**
- Produces:
  - `KbDraft`. All columns are NOT NULL unless marked otherwise:
    - `id`
    - `user_id` FK users CASCADE
    - `agent_id` FK agents SET NULL, nullable
    - `space_id` FK kb_spaces CASCADE
    - `folder_id` FK kb_folders SET NULL, nullable
    - `document_id` FK kb_documents CASCADE, nullable
    - `base_revision` int, nullable
    - `title` String(200), default ""
    - `body_md` Text, default ""
    - `brief` Text
    - `sources` JSONB list of `{"kind": "task"|"doc", "ref": str, "title": str, "text": str}`
    - `turn` JSONB, nullable
    - `session_ref` String, nullable
    - `created_at`, `last_activity_at`

    Unique index `(user_id, document_id)` WHERE `document_id IS NOT NULL`.
  - `KbDraftMessage`:
    - `id`
    - `draft_id` FK CASCADE, indexed
    - `author` String(10): `"person"|"agent"|"system"`
    - `text` Text
    - `target` JSONB, nullable: `{"section": str, "text": str}`
    - `run_id` FK agent_runs SET NULL, nullable
    - `created_at`
  - `AgentRun.draft_id` FK kb_drafts CASCADE, nullable, indexed.
  - Check constraint `agent_runs_target_check` becomes exactly one of `task_id`, `question_id`, `draft_id` not null.

- [ ] **Step 1: Write the failing tests**
  - `test_draft_run_needs_exactly_one_target`:
    - an `AgentRun` with both `task_id` and `draft_id` fails the flush with `IntegrityError`;
    - one with only `draft_id` flushes.
  - `test_one_draft_per_person_per_document`: a second `KbDraft` with the same `(user_id, document_id)` raises
    `IntegrityError`. Two new-document drafts (`document_id=None`) for one person are fine.
  - `test_deleting_the_document_deletes_its_drafts`.
- [ ] **Step 2: Run and see them fail.**
  - Run: `cd backend && uv run pytest tests/kb_drafts/test_models.py -q`
  - Expected: FAIL (import error, `app.kb_drafts.models`).
- [ ] **Step 3: Add the models.** Generate the migration against `megoo_migrate`. Hand-edit the migration to drop and
  re-create `agent_runs_target_check` as
  `(task_id IS NOT NULL)::int + (question_id IS NOT NULL)::int + (draft_id IS NOT NULL)::int = 1`, with a
  downgrade that restores the old expression. Update `CheckConstraint` in `agent_runs/models.py` to the same
  expression.
- [ ] **Step 4: Run the tests and see them pass.**
  - Run: `uv run pytest tests/kb_drafts/test_models.py -q`
  - Expected: 3 passed.
- [ ] **Step 5: Commit** `feat(kb-drafts): draft tables and the draft run target`.

### Task 2: Blocks, block diff and marks

**Files:**
- Create: `backend/app/kb_drafts/blocks.py`
- Modify: `backend/app/kb/service.py` (rename `_opcodes` → `opcodes`, keeping callers working)
- Test: `backend/tests/kb_drafts/test_blocks.py`

**Interfaces:**
- Consumes: `app.kb.service.opcodes(a: list[str], b: list[str]) -> list[tuple[str, int, int, int, int]]`.
- Produces:
  - `split_blocks(md: str) -> list[str]`: blocks separated by one or more blank lines. A fenced block (a line
    starting with ```` ``` ```` or `~~~`, up to its closing fence or the end) is one block even with blank lines
    inside. CRLF is normalised to LF. Each block is right-stripped, and empty blocks are dropped.
  - `join_blocks(blocks: list[str]) -> str`: `"\n\n".join(blocks)`.
  - `new_turn(request: str, before_md: str, after_md: str) -> dict | None`. The turn dict is `{"request", "before":
    [blocks], "after": [blocks], "ops": [[tag, a1, a2, b1, b2], ...], "status": {"<i>": "open"}}`. Mark `i` is the
    i-th non-equal op. It returns None when nothing changed.
  - `mark_kind(tag) -> "added"|"removed"|"changed"`: insert, delete, replace.
  - `compose(turn: dict) -> str`: equal ops take the `after` blocks. A mark with status `"undone"` takes its
    `before` blocks, any other status its `after` blocks. The result is joined with `join_blocks`.
  - `segments(turn: dict | None, body_md: str) -> list[dict]`:
    - with no turn: `[{"kind": "text", "md": body_md}]`;
    - otherwise a list where consecutive settled blocks merge into `{"kind": "text", "md"}`, and each open mark is
      `{"kind": "mark", "id": i, "change": mark_kind, "request": turn["request"], "old_md", "new_md"}`.
  - `open_count(turn) -> int`.

- [ ] **Step 1: Write the failing tests**
  - `test_fence_with_blank_lines_is_one_block`:
    ```python
    md = "Intro\n\n```\na\n\nb\n```\n\nEnd"
    assert split_blocks(md) == ["Intro", "```\na\n\nb\n```", "End"]
    ```
  - `test_unclosed_fence_runs_to_the_end`.
  - `test_turn_marks_added_changed_removed`:
    - before: `"# A\n\nold\n\nkeep1\n\nFAQ\n\nkeep2"`;
    - after: `"# A\n\nnew\n\nkeep1\n\nkeep2\n\n## Rollback"`.

    Assertions:
    - the open marks' `change` values in order are `["changed", "removed", "added"]`;
    - the first segment is the text `"# A"`;
    - `compose` with nothing undone equals the after text.
  - `test_undo_puts_back_the_before_blocks`: set one mark's status to `"undone"`. `compose` equals the before text
    for that span and the after text elsewhere.
  - `test_no_change_gives_no_turn`: `new_turn("x", "a", "a\n")` is None.
- [ ] **Step 2: Run and see them fail.**
  - Run: `uv run pytest tests/kb_drafts/test_blocks.py -q`
  - Expected: FAIL (import error).
- [ ] **Step 3: Implement `blocks.py`** with the signatures above. Use `app.kb.service.opcodes` on the block lists.
- [ ] **Step 4: Run the tests and see them pass.**
  - Run: `uv run pytest tests/kb_drafts/test_blocks.py tests/kb -q`
  - Expected: all pass (the kb tests prove the rename broke nothing).
- [ ] **Step 5: Commit** `feat(kb-drafts): block diff and marks`.

### Task 3: Draft API without runs (create, read, edit, marks, discard, agent)

**Files:**
- Create: `backend/app/kb_drafts/schemas.py`, `backend/app/kb_drafts/service.py`, `backend/app/kb_drafts/router.py`
- Modify: `backend/app/main.py` (include the router)
- Test: `backend/tests/kb_drafts/test_api.py`

**Interfaces:**
- Consumes: Task 1 models, Task 2 `blocks`, `app.kb.access.get_space_for(db, user, space_id, write=True)`,
  `app.agents.service.can_use_agent`, `is_usable_binding`, `app.runner.registry.is_available`.
- Produces (routes under `/api/kb/drafts`, all for the signed-in person):
  - `GET /agents?space_id=` → `list[DraftAgentOut{id, name, online: bool, runner_ok: bool}]`.
    - The list follows Global Constraints' agent choice, online first, then by name.
    - `runner_ok` means the agent's runner advertises `drafts/1`. Use
      `registry.agent_supports(id, DRAFTS_CAPABILITY)` when online, and the saved token capabilities when offline,
      as `agents/service.agent_problems` does.
    - Add `DRAFTS_CAPABILITY = "drafts/1"` to `app/runner/registry.py`.
  - `POST /` body `DraftIn{space_id, folder_id?, document_id?, agent_id, brief (1..20000 chars), sources:
    list[{kind: "task", key} | {kind: "doc", id}] (max 10)}` → `DraftOut`, 201.
    - **Existing draft:** with `document_id` and an existing draft of this person, it returns that draft with 200
      and ignores the brief.
    - **Sources:** they are read now with the person's access (task title + description, document title + body)
      into `sources`. More than 500,000 characters in total gives 422 `sources_too_large`. An unreadable source
      gives 404 `source_not_found`.
    - **Existing document:** it copies `title`, `body_md` and `base_revision = latest_revision` from it.
    - **First message:** it adds the brief as the first `person` message. Task 4 adds the first turn's run.
  - `GET /` → `list[DraftSummary{id, title, space: SpaceRef, document_id, agent: Named|None, last_activity_at}]`,
    newest activity first.
  - `GET /{id}` → `DraftOut`:
    - `id`, `title`, `body_md`;
    - `segments` (Task 2);
    - `open_marks: int`;
    - `messages: list[{id, author, text, target, created_at}]`;
    - `agent: DraftAgentOut | None`;
    - `space: SpaceRef`, `folder_path: str`;
    - `document: {id, latest_revision} | None`, `base_revision`;
    - `state: "idle"|"writing"|"waiting"` (Task 4 fills it; "idle" for now).
  - `PUT /{id}` body `{title?: str, body_md?: str}`: the person's edit.
    - It settles an open turn first (`turn = None`, body unchanged).
    - It refuses with 409 `agent_writing` while the draft has a queued or running run (Task 4 makes that possible).
  - `POST /{id}/settle`: keeps every open mark (`turn = None`).
  - `POST /{id}/marks/{mark_id}/keep` and `/undo`: set the status, then `body_md = compose(turn)`. When no mark is
    open, the turn is cleared. An unknown or settled mark gives 404 `mark_not_found`.
  - `POST /{id}/keep-all` and `/undo-all`.
  - `PATCH /{id}/agent` body `{agent_id}`: checks the agent the same way as create. Refused while a run is active
    (409 `agent_writing`). Clears `session_ref`.
  - `DELETE /{id}`: discard. Task 4 adds stopping the run and Task 6 adds `draft_done`.
  - **On every call:** another person's draft gives 404 `draft_not_found`. Lost write access to the space gives
    403 `forbidden`. An agent that fails the choice rule gives 422 `agent_not_available`.
  - **Events:** each change bumps `last_activity_at` and publishes `Event(type="kb_draft.updated",
    user_id=draft.user_id)`.

- [ ] **Step 1: Write the failing tests** (use the factories in `backend/tests/factories.py` and the kb tests'
  helpers):
  - `test_project_space_offers_usable_project_agents`
  - `test_team_space_offers_only_own_agents`
  - `test_start_copies_sources_with_the_persons_access`, including an unreadable task giving 404 `source_not_found`
  - `test_start_on_a_document_with_a_draft_returns_it`
  - `test_drafts_are_private` (another member gets 404)
  - `test_keep_and_undo_compose_the_body`: seed `turn` with `blocks.new_turn`, then undo one mark and assert
    `body_md`
  - `test_edit_settles_open_marks`
  - `test_lost_write_access_is_403`
  - `test_removed_agent_is_refused` (`PATCH /agent` to an unbound agent gives 422)
  - `test_discard_deletes_draft_and_messages`
- [ ] **Step 2: Run and see them fail.**
  - Run: `uv run pytest tests/kb_drafts/test_api.py -q`
  - Expected: FAIL (404s, no routes).
- [ ] **Step 3: Implement the schemas, service and router.** Service functions are named after the routes
  (`list_agents`, `start_draft`, `get_draft_for`, `edit`, `settle`, `set_mark`, `set_all`, `change_agent`,
  `discard`). `get_draft_for(db, user, draft_id) -> KbDraft` locks the row (`with_for_update`) for writes.
- [ ] **Step 4: Run the tests and see them pass.**
  - Run: `uv run pytest tests/kb_drafts -q`
  - Expected: all pass.
- [ ] **Step 5:** Run `npm run gen:api` in `frontend/`, then **commit** `feat(kb-drafts): draft API`.

### Task 4: Turns as agent runs

**Files:**
- Create: `backend/app/kb_drafts/turns.py`, `backend/app/kb_drafts/prompts.py`,
  `backend/app/workflow/methodology_texts/defaults/kb_draft.md`
- Modify:
  - `backend/app/workflow/methodology.py` (`OTHER_KEYS = {"kb": ["kb_draft"]}`, with `ALL_KEYS` and a `GROUP_OF`
    covering it);
  - `backend/app/workflow/methodology_history.py` (`DEFAULT_HISTORY["kb_draft"]`);
  - `backend/app/workflow/router.py` (the methodology `stage` field becomes `str` from `GROUP_OF`, and the key check
    uses `ALL_KEYS`);
  - `backend/app/agent_runs/service.py`: `_claim_next`, `_send_start`, `_transition`, `cancel_run`, and every place
    that special-cases `question_id` (grep it: 21 hits) gets the matching `draft_id` case;
  - `backend/app/runner/protocol.py` (`RunStart.draft: RunDraft | None = None`, `RunDraft{id: str}`);
  - `backend/app/kb_drafts/router.py`, `service.py`.
- Test: `backend/tests/kb_drafts/test_turns.py`

**Interfaces:**
- Consumes:
  - Task 3 service;
  - `app.notifications.service.notify(db, user_ids, Kind.needs_you, title=, body=, link=)`;
  - `read_by_acting(db, user_id, link=)`;
  - `app.workflow.methodology.current(db, key)`.
- Produces:
  - `POST /api/kb/drafts/{id}/requests` body `{text: 1..20000, target: {section, text} | null}` → `DraftOut`.
    - It settles the open turn, adds a `person` message and enqueues a run.
    - It refuses with 409 `agent_writing` when a run is queued or running, and 422 `agent_not_available` when
      the agent is gone or not allowed.
    - Starting a draft (Task 3's `POST /`) now also enqueues the first turn, with the brief as its request.
  - `POST /api/kb/drafts/{id}/stop`: cancels the active run with `cancel_run`.
  - `turns.enqueue_turn(db, draft, *, request: str, target: dict | None, newer: dict | None = None) -> AgentRun`:
    creates `AgentRun(draft_id=, agent_id=draft.agent_id, requested_by=draft.user_id, policy="read_only",
    prompt=, resume_session_ref=draft.session_ref, resume_prompt=, methodology_version_id=,
    draft_request={"request", "target", "newer", "submitted": False})`.
    - `draft_request` is a new nullable JSONB column on `agent_runs`, added in this task's migration, so
      `kb_draft_read` returns exactly what this run was asked.
    - It also calls `read_by_acting(db, draft.user_id, link=f"/kb/drafts/{draft.id}")`.
  - `prompts.turn_prompt(db, draft, request, target) -> tuple[str, str, MethodologyVersion]` returns `(prompt,
    resume_prompt, version)`:
    - **prompt:** the `kb_draft` methodology text, the brief, and "Call kb_draft_read, then kb_draft_submit once";
    - **resume_prompt:** just this turn's request and target.
  - `turns.start_fields(db, run) -> tuple[RunTask, str, dict]`, like `a2a/routing.start_fields`:
    - `RunTask(key=f"KBD-{draft.id.hex[:12]}", title=draft.title or "Draft", description_md="",
      project_key=<project key or "">)`;
    - `local_path` is the binding's path for project drafts, else `""`;
    - fields `role="kb_draft"`, `mcp=McpAccess(...)`, `resume_session_id`, `resume_prompt`, `draft=RunDraft(id)`.
    - It raises `NotSupported` (fail the run) when the draft or agent is gone, or the binding is unusable.
  - `turns.on_run_finished(db, run)`, called from `_transition` for draft runs:
    - stores `draft.session_ref = run.session_ref`;
    - adds a system message when the run failed or was cancelled ("<agent> stopped before changing the draft." /
      "<agent> couldn't finish: <reason>");
    - publishes `kb_draft.updated`;
    - notifies the person with `"<agent> updated your draft '<title>'"` (body: the reply's first line, link
      `/kb/drafts/{id}`) when `run.draft_request["submitted"]` is true.
  - `DraftOut.state`:
    - `"writing"` when a run is running;
    - `"waiting"` when one is queued and the agent is offline;
    - `"idle"` otherwise.
  - In `_claim_next`, draft runs need `DRAFTS_CAPABILITY`. One running run per draft, as per question.

- [ ] **Step 1: Write the failing tests**
  - `test_request_queues_a_read_only_draft_run`: `run.draft_id`, `policy == "read_only"` and
    `run.resume_session_ref` equal to the draft's `session_ref`.
  - `test_second_request_while_writing_is_409`.
  - `test_runner_without_drafts_capability_leaves_the_run_queued`, using the fake registry helpers the
    `agent_runs` tests use.
  - `test_start_fields_for_team_draft_have_no_local_path` and `test_start_fields_for_project_draft_use_binding`.
  - `test_cancelled_run_adds_a_system_message_and_keeps_the_body`.
  - `test_finished_run_with_submission_notifies_the_person`: set `run.draft_request["submitted"] = True`, finish
    the run, and assert one `needs_you` notification with the exact title. A run without the flag notifies no one.
  - `test_methodology_lists_kb_draft_in_the_kb_group`: GET of the methodology list contains `{"key": "kb_draft",
    "stage": "kb"}`.
  - `test_default_history_has_kb_draft`: the existing default-history test covers it once the file is added.
- [ ] **Step 2: Run and see them fail.**
  - Run: `uv run pytest tests/kb_drafts/test_turns.py -q`
  - Expected: FAIL.
- [ ] **Step 3: Implement.** The `kb_draft.md` methodology text tells the agent to:
  - read with `kb_draft_read`;
  - change only what the request asks (only the target, when one is given);
  - keep the person's text and edits;
  - never change files;
  - propose a title only when the draft has none, and otherwise change it only when asked;
  - submit the whole new draft once with `kb_draft_submit(body_md, reply, title?)`;
  - make the reply one or two sentences saying what it did, ask a question there if unsure, and never repeat the
    document.

  Add the sha256 to `DEFAULT_HISTORY`. Generate the `draft_request` migration against `megoo_migrate`.
- [ ] **Step 4: Run the tests and see them pass.**
  - Run: `uv run pytest tests/kb_drafts tests/agent_runs tests/workflow/test_methodology*.py -q`
  - Expected: all pass.
- [ ] **Step 5:** Run `npm run gen:api`, then **commit** `feat(kb-drafts): agent turns`.

### Task 5: MCP tools for draft runs

**Files:**
- Create: `backend/app/mcp_server/kb_draft_tools.py`
- Modify:
  - `backend/app/mcp_server/server.py` (register);
  - `backend/app/mcp_server/auth.py` (`require_run_task` refuses draft runs);
  - `backend/app/mcp_server/kb_tools.py` (`_check_role`: draft runs may search, list and read, never `kb_write`);
  - `backend/app/kb_drafts/turns.py` (`apply_submission`).
- Test: `backend/tests/kb_drafts/test_mcp.py`

**Interfaces:**
- Consumes: `current_run`, `tool_session()`, Task 2 `blocks.new_turn`, Task 4 `AgentRun.draft_request`.
- Produces:
  - `kb_draft_read() -> {"brief", "title", "body_md", "request", "target", "newer_version": {"revision",
    "body_md"} | None, "sources": [...], "conversation": [last 20 messages {author, text}]}`.
    - The draft is the run's own (`current_run.draft_id`); no id is passed.
    - Any other run, or a personal token, gets `not_allowed_in_role`.
  - `kb_draft_submit(body_md: str, reply: str (1..4000), title: str | None = None) -> {"ok": true, "changes": n}`
    calls `turns.apply_submission(db, run, body_md, reply, title)`:
    - checks the size (`too_large`);
    - refuses a second call in one run (`already_submitted`, tracked in `run.draft_request["submitted"]`);
    - refuses when the draft is gone (`draft_gone`);
    - sets `draft.turn = blocks.new_turn(request, draft.body_md, body_md)` and
      `draft.body_md = blocks.join_blocks(blocks.split_blocks(body_md))`;
    - sets the title when given;
    - adds the `agent` message with `run_id`;
    - publishes `kb_draft.updated`.

- [ ] **Step 1: Write the failing tests**
  - `test_submit_marks_changes_against_the_current_draft`: the person edits the draft after the request was queued.
    The submission's marks diff against the edited text, and the edit survives where the agent kept it.
  - `test_second_submit_is_refused`.
  - `test_submit_after_discard_is_draft_gone`.
  - `test_task_run_cannot_use_draft_tools`.
  - `test_draft_run_cannot_kb_write_or_use_task_tools`: `kb_write` and `get_task` give `not_allowed_in_role`.
  - `test_read_returns_the_runs_own_request_and_target`.
- [ ] **Step 2: Run and see them fail.**
  - Run: `uv run pytest tests/kb_drafts/test_mcp.py -q`
  - Expected: FAIL.
- [ ] **Step 3: Implement**, following `a2a_tools.submit_answer` for the shape and the `tests/mcp` helpers for
  calling tools under a run token.
- [ ] **Step 4: Run the tests and see them pass.**
  - Run: `uv run pytest tests/kb_drafts tests/mcp -q`
  - Expected: all pass.
- [ ] **Step 5: Commit** `feat(kb-drafts): MCP tools for the writing agent`.

### Task 6: Save, conflict, bring in, discard and runner clean-up

**Files:**
- Modify:
  - `backend/app/kb_drafts/service.py`, `router.py`;
  - `backend/app/runner/protocol.py` (`DraftDone{type: "draft_done", agent_id, draft_id}`);
  - `backend/app/kb/service.py` (`delete_document` stops runs of the document's drafts first);
  - `frontend/src/components/kb/RevisionHistory.tsx` (`who` renders `"<person> with <agent>"`), with its test
    updated.
- Test: `backend/tests/kb_drafts/test_save.py`

**Interfaces:**
- Consumes: `app.kb.service.create_document(..., agent_id=, summary=)`, `update_document(..., base_revision=,
  agent_id=, summary=)`, `registry` connection lookup for an agent.
- Produces:
  - `POST /api/kb/drafts/{id}/save` body `{summary?: str (max 200), force?: bool}` → `{document_id}`.
    - Refused while a run is active (409 `agent_writing`).
    - The summary defaults to `"Written with <agent>"`.
    - **New document:** `create_document` in the draft's space and folder (`title_taken` passes through as 409).
    - **Existing document:** `update_document(base_revision=draft.base_revision)`. A 409 `kb_conflict` passes
      through unless `force`, which uses the document's latest revision.
    - **Then:** delete the draft, send `draft_done`, `read_by_acting(link=)`, and publish both `kb_draft.updated`
      and the kb event.
  - `POST /api/kb/drafts/{id}/bring-in` → `DraftOut`:
    - sets `base_revision` to the document's latest;
    - enqueues a turn with request "Someone saved a newer version (rev N). Bring their changes into the draft and
      keep ours where they don't conflict." and `newer={"revision", "body_md"}`.
  - `turns.send_draft_done(agent_id, draft_id)`: best effort. It does nothing when the agent's runner isn't
    connected or lacks `drafts/1`. Called by save and discard. Discard also cancels an active run first.

- [ ] **Step 1: Write the failing tests**
  - `test_save_new_document_credits_person_and_agent`: revision 1 has `author_user_id`, `author_agent_id` and
    summary "Written with laptop-claude".
  - `test_save_existing_document_conflict_then_force`.
  - `test_bring_in_moves_the_base_and_queues_a_turn_with_the_newer_text`.
  - `test_save_with_runner_offline_still_succeeds`.
  - `test_discard_cancels_the_running_turn`.
  - `test_deleting_the_document_stops_draft_runs`.
- [ ] **Step 2: Run and see them fail.**
  - Run: `uv run pytest tests/kb_drafts/test_save.py -q`
  - Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and see them pass.**
  - Run: `uv run pytest -q -n auto` (whole backend suite, alone)
  - Expected: all pass. Also run `npm test -- RevisionHistory` in `frontend/` (pass).
- [ ] **Step 5:** Run `npm run gen:api`, then **commit** `feat(kb-drafts): save, bring in, discard`.

### Task 7: Runner — draft folders

**Files:**
- Create: `runner/internal/drafts/drafts.go`, `runner/internal/drafts/drafts_test.go`
- Modify:
  - `runner/internal/protocol/protocol.go`:
    - `CapabilityDrafts = "drafts/1"`, added to `NewHello`;
    - `RunStart.Draft *RunDraft \`json:"draft,omitempty"\``, with `RunDraft{ID string \`json:"id"\`}`;
    - `TypeDraftDone`, `DraftDone{Type, AgentID, DraftID}`.
  - `runner/internal/jobs/manager.go`:
    - `Dispatch` handles `draft_done`;
    - `drive` branches for `rs.Draft != nil`;
    - `bindingPath` lets a draft run with an empty `Task.ProjectKey` through;
    - `Serve` starts the sweep.
- Test: `runner/internal/jobs/drafts_test.go`, plus the protocol tests

**Interfaces:**
- Produces:
  - `drafts.Ensure(ctx context.Context, cacheRoot, agentID, draftID, repo string) (string, error)`:
    - the path is `cacheRoot/drafts/<agentID>/<draftID>`, with ids validated like `worktree.safeID`;
    - with a non-empty `repo` it makes a detached worktree at the repo's HEAD (`git worktree add --detach`), or
      reuses an existing healthy one;
    - otherwise it makes an empty directory;
    - either way it writes `.megoo-draft-touched` with the current time.
  - `drafts.Remove(cacheRoot, agentID, draftID, repo string) error`: `git worktree remove --force --force` when it
    is a worktree, then `os.RemoveAll`, then `git worktree prune`.
  - `drafts.Sweep(cacheRoot string, maxAge time.Duration, now time.Time, repoOf func(agentID string) []string)
    []error` removes draft folders whose touch file is older than `maxAge`. The constant is `SweepAge = 30 * 24 *
    time.Hour`. It runs at `Serve` start and every 24 h.
  - **`drive` for a draft run:**
    - it skips `worktree.EnsureFrom`, the start-branch report, `gitstate.Pin`, git capture, Materialize,
      CommitRepoFiles and the read-only branch-prefix check;
    - it uses `drafts.Ensure`, then `policy.New(kind, dir)`, images and `startAdapter` as usual;
    - it reports no git state in `run_finished`.

- [ ] **Step 1: Write the failing tests**
  - `TestEnsureEmptyFolderPersistsAcrossCalls`
  - `TestEnsureProjectDraftIsDetachedWorktree`: `git -C <dir> symbolic-ref -q HEAD` fails (detached), and no new
    branch exists.
  - `TestRemoveDropsWorktreeRegistration`
  - `TestSweepRemovesOnlyOldFolders`
  - `TestEnsureRejectsUnsafeIDs`
  - In jobs:
    - `TestDraftRunWorksInDraftFolder`: the fake agent's report `Cwd` is the draft folder, and the run finishes
      `completed`;
    - `TestDraftDoneRemovesFolder`.
  - In protocol: `TestHelloAdvertisesDrafts` and wire names for `draft` and `draft_done`.
- [ ] **Step 2: Run and see them fail.**
  - Run: `cd runner && go test ./internal/drafts/ ./internal/jobs/ ./internal/protocol/`
  - Expected: FAIL (undefined).
- [ ] **Step 3: Implement**, reusing `worktree.lockPath`'s pattern (export a `LockPath`, or copy the small mutex
  map into `drafts`).
- [ ] **Step 4: Run the tests and see them pass.**
  - Run: `go test ./...`
  - Expected: ok. The known flaky `TestSteerAfterTurnEndsReportsNotRunningAndCancelsStrayTurn` may fail
    intermittently. Rerun it alone before treating a failure as yours.
- [ ] **Step 5: Commit** `feat(runner): draft folders for knowledge base drafting`.

### Task 8: Frontend — starting a draft and finding it again

**Files:**
- Create: `frontend/src/lib/kbDrafts.ts`, `frontend/src/components/kb/drafts/StartDraftDialog.tsx`,
  `frontend/src/components/kb/drafts/MyDrafts.tsx`, `frontend/src/components/kb/drafts/DraftBanner.tsx`
- Modify:
  - `frontend/src/lib/realtime.ts` (`case "kb_draft": return [["kb-drafts"]]`);
  - `frontend/src/app/(app)/kb/[spaceId]/page.tsx` ("Write with an agent" beside "New document");
  - `frontend/src/components/kb/DocView.tsx` ("Write with an agent" beside Edit, and `DraftBanner`);
  - `frontend/src/app/(app)/kb/page.tsx` (`MyDrafts` above the spaces).
- Test: `frontend/src/components/kb/drafts/__tests__/StartDraftDialog.test.tsx`, `MyDrafts.test.tsx`,
  `frontend/src/lib/__tests__/realtime.test.ts` (extend)

**Interfaces:**
- Consumes: Task 3 and 4 routes, and the generated `S["DraftOut"]`, `S["DraftSummary"]` and `S["DraftAgentOut"]`.
- Produces:
  - `kbDraftKeys = { all: ["kb-drafts"], list: () => ["kb-drafts", "list"], one: (id) => ["kb-drafts", id], agents:
    (spaceId) => ["kb-drafts", "agents", spaceId] }`;
  - `useKbDrafts()`, `useKbDraft(id)`, `useDraftAgents(spaceId)`.
  - `StartDraftDialog({ spaceId, folderId, document?, onClose })`:
    - the agent select (offline agents marked "(offline)"; agents with `runner_ok` false are disabled with "runner
      needs updating");
    - the brief textarea, labelled "What should this document be?", or "What should the agent change?" for an
      existing document;
    - "Let it read" chips: a task key input and a document search reusing `useKbSearch`;
    - "Save into" for new documents;
    - **Start drafting** posts and navigates to `/kb/drafts/{id}`.
    - With no agents it shows "No agent can work on this project" (project space) or "You have no agents".

- [ ] **Step 1: Write the failing tests:**
  - the dialog lists only returned agents with the offline mark;
  - an empty list shows the space-kind message;
  - submit posts the body and routes;
  - `MyDrafts` renders rows linking to `/kb/drafts/{id}`, and nothing when empty;
  - `invalidationsFor({type: "kb_draft.updated"})` gives `[["kb-drafts"]]`.
- [ ] **Step 2: Run and see them fail.**
  - Run: `cd frontend && npm test -- drafts realtime`
  - Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and see them pass.** Same command; expected pass. Then `npx tsc --noEmit` and
  `npm run lint` (clean).
- [ ] **Step 5: Commit** `feat(kb-drafts): start a draft, My drafts`.

### Task 9: Frontend — the writing page

**Files:**
- Create:
  - `frontend/src/app/(app)/kb/drafts/[draftId]/page.tsx`;
  - `frontend/src/components/kb/drafts/DraftPage.tsx`, `DraftView.tsx`, `DraftConversation.tsx`;
  - `frontend/src/lib/wordDiff.ts`;
  - `frontend/src/components/kb/MarkdownField.tsx`, the textarea, count and preview extracted from `DocEditor`,
    which then uses it.
- Test: `frontend/src/components/kb/drafts/__tests__/DraftView.test.tsx`, `DraftPage.test.tsx`,
  `frontend/src/lib/__tests__/wordDiff.test.ts`, plus `DocEditor`'s existing tests still passing

**Interfaces:**
- Consumes: `useKbDraft`, the Task 3 and 4 routes, `KbMarkdown`.
- Produces:
  - `wordDiff(a: string, b: string) -> { op: "same"|"del"|"add", text: string }[]`: an LCS over
    whitespace-separated tokens. When `a.length * b.length` tokens exceed 40,000, it falls back to `[del a, add b]`.
  - **`DraftView`** renders `segments`:
    - text segments go through `KbMarkdown`;
    - **added marks** are green (`border-green`);
    - **removed marks** are pink, with the text struck through;
    - **changed marks** are amber, rendered as `wordDiff(old_md, new_md)` in plain text: `del` struck pink, `add`
      green;
    - each mark shows its request and **Keep** / **Undo** buttons (at least 32 px tall).
  - **Top bar:** "Draft · not saved", the open-change count with **Keep all** / **Undo all** (hidden at 0), an
    editable title input, **Save to KB…** and **Discard draft** (Task 10 wires the last two).
  - **Selection target:** a `mouseup`/`selectionchange` inside `DraftView` sets the target. The section is the
    nearest preceding heading in the segment's markdown, or "Top". The text is the selection, capped at 2,000
    characters.
  - **`DraftConversation`:**
    - messages (person right, agent left, system muted);
    - "<agent> is writing…" with **Stop** when `state === "writing"`;
    - "Waiting for <agent> to come online" when `state === "waiting"`;
    - target chips;
    - a composer that posts to `/requests`, disabled while writing;
    - an agent picker when `agent` is null or not allowed, which PATCHes `/agent`.
  - **Editing toggle** ("Edit text" / "Done editing"):
    - it settles the open marks first (`POST /settle`), labelled "Keeps the N open changes" when N > 0;
    - it then shows `MarkdownField` and title edits, saved with `PUT /{id}` on "Done editing";
    - it is disabled while writing, with the banner "<agent> is writing… the draft is read-only until it
      finishes".
  - **Layout:**
    - `lg:` two columns (`minmax(0,1fr) 360px`);
    - below `lg`, a tablist of **Draft** / **Conversation**, with the composer fixed at the bottom of both tabs;
    - nothing overflows at 280 px.
  - **Unsaved edits:** `useUnsavedGuard` while the editing toggle has unsent text.

- [ ] **Step 1: Write the failing tests**
  - `wordDiff("a b c", "a x c")` gives `[same "a", del "b", add "x", same "c"]`, with whitespace kept.
  - `DraftView`:
    - a changed segment shows the struck old word and the new word;
    - **Undo** posts to `/marks/0/undo`;
    - **Keep all** appears only when `open_marks > 0`.
  - `DraftPage`:
    - while writing, the composer and the editing toggle are disabled and **Stop** posts to `/stop`;
    - selecting text in the draft sets the chip "About: selected text in 'Prerequisites'";
    - the editing toggle with open marks shows "Keeps the 2 open changes" and posts `/settle` before showing the
      editor.
  - `DocEditor`'s existing tests stay green after the extraction.
- [ ] **Step 2: Run and see them fail.**
  - Run: `npm test -- drafts wordDiff DocEditor`
  - Expected: the new ones FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and see them pass.** Same command, then `npx tsc --noEmit`, `npm run lint`, and
  `npm test` (whole web suite).
- [ ] **Step 5: Commit** `feat(kb-drafts): the writing page`.

### Task 10: Frontend — save, conflict, discard and the methodology tab

**Files:**
- Create: `frontend/src/components/kb/drafts/SaveDraftDialog.tsx`
- Modify: `DraftPage.tsx`, `frontend/src/components/workflow/MethodologyEditor.tsx` (a `{ id: "kb", label:
  "Knowledge base", keys: ["kb_draft"] }` card, and `METHODOLOGY_STAGES` gains `"kb"`)
- Test: `frontend/src/components/kb/drafts/__tests__/SaveDraftDialog.test.tsx`, plus `MethodologyEditor`'s test

**Interfaces:**
- Consumes: Task 6 routes, the KB diff route `GET /api/kb/documents/{id}/diff?a=&b=`, `DiffView`, `useConfirm`.
- Produces:
  - **`SaveDraftDialog`:**
    - a summary input (placeholder "Written with <agent>");
    - "N changes not reviewed" when `open_marks > 0`;
    - Save posts `/save`, then routes to `/kb/doc/{document_id}`.
  - **On 409 `kb_conflict`:**
    - the dialog shows "Someone saved a newer version.";
    - **Show what changed** shows the `DiffView` of `base_revision` to `latest_revision`;
    - **Ask the agent to bring it in** posts `/bring-in` and closes;
    - **Save over it anyway** confirms, then posts `/save` with `force: true`.
  - **`title_taken`:** shows the error, and the title stays editable in the top bar.
  - **Discard draft:** confirms ("Discard this draft?" / "The draft and its conversation are deleted."), deletes,
    then routes to the document or the space.

- [ ] **Step 1: Write the failing tests:**
  - unreviewed count text;
  - conflict flow buttons and their requests;
  - force confirm;
  - discard confirm, then DELETE;
  - the methodology editor shows a "Knowledge base" tab with `kb_draft`.
- [ ] **Step 2: Run and see them fail.**
  - Run: `npm test -- SaveDraftDialog MethodologyEditor`
  - Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and see them pass.** Same command, then `npm test`, `npx tsc --noEmit` and
  `npm run lint`.
- [ ] **Step 5: Commit** `feat(kb-drafts): save, conflict and discard`.

### Task 11: End-to-end

**Files:**
- Create: `frontend/e2e/kb-drafts.spec.ts`
- Modify: `frontend/e2e/mobile.spec.ts` (the writing page at 280 px)

**Interfaces:**
- Consumes:
  - `frontend/e2e/helpers/runner.ts` (`buildBinaries`, `startRunner` with a scenario);
  - the fake agent's `mcp_call` step (`runner/internal/fakeagent/scenario.go` `McpStep`), calling
    `kb_draft_submit`.

- [ ] **Step 1: Write the spec**, following `chats.spec.ts` for the runner setup:
  1. A project document "Deploying payments" with sections Overview, Prerequisites and FAQ.
  2. **Write with an agent** → the brief → **Start drafting**.
  3. The fake agent's first run submits a body that adds "## Rollback" and removes "## FAQ". Both marks show.
  4. **Undo** the removal: FAQ is back unmarked.
  5. **Edit text**: type "Owner: payments team." under Overview, then **Done editing**.
  6. Request "shorten the prerequisites". The second scenario run reads the draft, asserting that the read result
     contains "Owner: payments team.", and submits a changed Prerequisites while keeping that line.
  7. A changed mark shows. **Keep all**.
  8. **Save to KB…** → Save. The document page shows the text. History shows rev 2 by "<person> with <agent>".

  In `mobile.spec.ts`:
  - at 280 px the writing page has **Draft** and **Conversation** tabs;
  - `document.documentElement.scrollWidth <= 280`.
- [ ] **Step 2: Run it.** Expect it to pass once the feature is complete; fix what it finds.
  - Run: `SPECS="kb-drafts.spec.ts mobile.spec.ts" bash <scratchpad>/e2e-mobile.sh`
  - Expected: all pass.
- [ ] **Step 3: Commit** `test(kb-drafts): end-to-end drafting with an agent`.
