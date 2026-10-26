# MegooColab Plan 6 — Agent-to-Agent Questions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An agent or a person asks **a project** a question about its code. MegooColab first offers matching Knowledge Base and memory entries, then routes the question to an online runner of a project member whose agent has that repository. A short **read-only** session answers it, citing files and lines. Manual-mode agents need their owner's approval (with edits) before the answer goes out; auto-mode agents answer directly. Questions wait in a queue while no runner is online, and project members can always answer directly. Every answer is filed in the target project's Knowledge Base, fed to memory, and delivered back to the asking task.

**Architecture:**
- **Backend:** a new `a2a` module.
  - `Question` rows are addressed to a target project.
  - An answering session is an ordinary `AgentRun` that points at the question instead of a task: `task_id` becomes nullable, a `question_id` column is added, and a check constraint requires exactly one of the two. It therefore reuses the runner dispatch, capacity, cancel, the run token and the R1 read-only check.
  - Routing runs in the Plan 4 job queue (`a2a.route`): periodically, when a question is asked, and when a runner connects.
  - Answers are filed through `kb.service`, and memory reads them through the `"answer"` source kind that Plan 5 reserved.
- **Runner:** unchanged. An answering run is a v2 `run_start` with `role="answer"`, `policy="read_only"`, the run's MCP token, and the synthetic task key `<TARGET>-Q<n>` (a worktree on branch `megoo/<TARGET>-Q<n>-<slug>` from the bound checkout's HEAD).
- **Frontend:** a Questions page (ask with suggestions, my questions, incoming per project with answer/approve), a "Questions to other projects" section and a "Waiting on" badge on the task view, and the project page's incoming questions.

**Tech Stack:** Plans 1–5 stack, no new dependencies.

**Spec:** [docs/brd.md](../../brd.md). This plan covers:
- §6.6 A2A-1 to A2A-7
- KB-4 (agent-to-agent Q&A filed in the KB)
- MEM-2 (agent-to-agent Q&A as a memory input)
- AGT-31 ("ask another project's agents")
- NFR-3 (questions are untrusted; answering sessions are read-only)
- the §8 worker's "question routing" duty
- success criterion §11 #4/#5 ("answered without a human relaying it, and the same question asked later is answered from KB/memory")

**Builds on:** Plans 1–5 on `main`. Reuse:
- **Agent runs:**
  - `agent_runs.service` (`dispatch_pending`, `_claim_next`, `_send_start`, `apply_update`, `finish_run`, `cancel_run`, `_transition`, `issue_run_token`)
  - `agents.service` (`owner_can_access`, `agent_statuses`)
  - `runner.registry` (`supports`, `WORKFLOW_CAPABILITY`)
- **Workflow context:** `workflow.context.wrap_untrusted` and `_escape`, and `context_providers` together with `_provided`
- **Knowledge Base and memory:**
  - `kb.service.create_document`, `ensure_folder`, `free_title`, `kb.access.space_for_project`, `kb.search.search`
  - `memory.search.search_conclusions`, `memory.sources.SOURCE_LOADERS` and `queue_extract`
- **Job queue:** `jobs.queue` (`enqueue`, `register`, `register_periodic`)
- **MCP:** `mcp_server.auth` (`tool_session`, `current_run`) and the `KB_TOOL_ROLES` pattern
- **Shared:** `audit.record`, `Event`/`publish`, `NoNulStr`, `get_project_for`, `accessible_project_ids`, `get_task_for`
- **Frontend:** `Markdown`, `.kb-prose`, `errorMessage`, `useProjects`

## Global Constraints

**Questions (A2A-1)**
- Fields:
  - `title` 1–200 (`NoNulStr`; when omitted, the first line of the body cut to 200)
  - `body` 1–4,000
  - `context` 0–8,000 (errors, what was tried)
  - `target_project_id` (CASCADE)
  - `from_task_id` | None (SET NULL)
  - `asked_by_user_id` (SET NULL)
  - `asked_by_agent_id` | None (SET NULL)
  - `number`: per target project, 1, 2, … from `projects.next_question_number`
- Statuses:

  | Status | Meaning |
  |---|---|
  | `queued` | waiting for a runner |
  | `routed` | an answering run is queued or running |
  | `draft` | waiting for the answering agent's owner |
  | `needs_human` | routing gave up |
  | `answered` | done |
  | `withdrawn` | the asker withdrew it |

- **Who may ask:** any active user whose role is not `viewer`, and their agents through MCP. The asker does not need access to the target project. To address a question, `GET /api/questions/targets` lists every project's `{key, name}` to signed-in users.
- An answering run cannot ask (no question loops).
- **Who may see a question:** admins, members of the target project (`accessible_project_ids`), the asking user, and members of the asking task's project. Anyone else gets 404.
- **Open-question cap:** at most 20 open questions (`queued|routed|draft|needs_human`) per asking user; beyond that, 429 `too_many_open_questions`.

**Suggestions before routing (A2A-6)**
- `suggest(db, user, project_id, text) -> list[Suggestion]` returns at most 5 items, `{kind: "kb"|"memory", id, title, snippet ≤ 300, link}`:
  - KB hybrid search hits in the target project's space (the Q&A folder and everything else there), and memory conclusions from `search_conclusions(project_id=…)`.
  - Restricted to what the **asker** can read; the target project may hold nothing they can read.
- The ask response includes the suggestions. The asker can withdraw the question when a suggestion answers it.

**Routing (A2A-2, A2A-5)**
- **Candidates:** agents that meet all of these:
  - have a binding to the target project
  - have an owner who can access it (`owner_can_access`)
  - are `online` or `busy` with spare capacity, on a runner supporting `workflow/1`
  - are not in the question's `tried_agent_ids`
- Pick the candidate with the fewest active runs, ties broken by `agent.id`. Create `AgentRun(question_id, agent_id, requested_by=asker, policy=read_only, prompt=<answer prompt>)` and set the question to `routed`.
- With no candidate, the question stays `queued`.
- `a2a.route` routes up to 50 queued questions per run. It runs every 60 s (periodic), on ask (dedupe `"a2a.route"`), and when a runner says hello.
- An answering run that ends **without** a submitted answer (failed, cancelled, or completed without `submit_answer`) adds its agent to `tried_agent_ids` and `attempts += 1`. At 3 attempts the status becomes `needs_human`; otherwise it goes back to `queued`.
- The "waiting on" badge: a task with open questions shows `waiting_on: [target project keys]`.

**The answering session (A2A-3, A2A-7)**
- `run_start`: `role="answer"`, `policy="read_only"`, `task = {key: "<TARGET>-Q<n>", title: question title, description_md: "", project_key: <TARGET>}`, `mcp` with the run token. There are no files.
- The prompt is fixed in `app/a2a/prompts.py`:
  - read code only
  - cite every claim as `path:start-end`
  - never reveal secrets, credentials, tokens or environment values
  - answer only the question
  - finish with `submit_answer`

  The question's title, body and context sit inside `<untrusted source="question">`.
- Run-token tools for answer runs:

  | Tool | Allowed |
  |---|---|
  | `get_question`, `submit_answer` | yes |
  | KB `kb_search`, `kb_read`, `kb_list` | yes |
  | `search_memory`, `ask_memory` | yes |
  | everything else (task, workflow, `kb_write`, ask tools) | refused with `not_allowed_in_role` |

- **Answers:** `answer_md` 1–20,000; `citations` ≤ 50 items, each `{path ≤ 500, start_line ≥ 1, end_line ≥ start_line}`.
- **Secret scrubbing:** before anything is stored, `scrub(text) -> (text, redacted: bool)` replaces likely secrets with `[redacted]`:
  - AWS access keys `AKIA[0-9A-Z]{16}`
  - `-----BEGIN [A-Z ]*PRIVATE KEY-----` blocks
  - `sk-[A-Za-z0-9_-]{20,}`, `gh[pousr]_[A-Za-z0-9]{36,}`, `xox[abposr]-[A-Za-z0-9-]{10,}`
  - `(?i)(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S+` (the value only)
  - `mgc_…`/`mgr_…` MegooColab tokens
- **Answer modes (A2A-4):**
  - **auto:** `answered` immediately.
  - **manual:** `draft`, with the draft stored. The owner (or an admin) approves with an optional edit, which gives `answered` (the edit is scrubbed too). A rejection with a reason adds the agent to `tried_agent_ids`, sets the status back to `queued`, and records the reason.
- **Human answers (A2A-5):** non-viewer members of the target project and admins may answer while the status is `queued|routed|draft|needs_human`. That cancels an active answering run (`cancel_run`) and gives `answered` with `answer_source="human"`.

**After an answer (A2A-6, KB-4, MEM-2)**
- Filed in the target project's KB under folder `Q&A`, titled `Q<n>: <title>` (`free_title` on a clash).
  - Body sections: `## Question` (body), `## Context` (if any), `## Answer` (answer), `## Sources` (citations as `` `path:start-end` `` lines).
  - The author is the answering agent's owner plus the agent, or the human who answered. The document id is stored on the question.
- Memory: `queue_extract(db, "answer", question.id)`. The `"answer"` loader returns title, body and answer, in project scope, with label `Q<n> to <TARGET>: <title>` and link `/questions/<id>`.
- **Delivery:**
  - When `from_task_id` is set: a task event `question_answered {question_id, target_key, number}` on the asking task, and `task.updated`.
  - The workflow context provider `a2a_context` adds `## Answers from other projects` (≤ 6,000 chars, each answer wrapped `<untrusted source="answer">`) for answered questions from that task.
  - MCP `get_question` returns the answer.
- **Events:** `question.updated` with `project_id = target project` (members' live views), plus a per-user event to the asker (`user_id`).

**Audit:**
- `a2a.question.asked`, `a2a.question.answered`, `a2a.question.withdrawn`
- `a2a.answer.approved`, `a2a.answer.rejected`, `a2a.answer.redacted` (when `scrub` changed anything)

## Review Focus

1. **Leaks across project boundaries.** An outsider reading another project's questions or answers through the list, detail, suggestions, MCP or prompt context. An answer that echoes a secret it read (scrubbing). A suggestion that reveals a KB document or conclusion the **asker** cannot read. Tested in Tasks 2, 4 and 6.
2. **A runner disappears mid-answer, or answers nothing.** The run fails or completes without `submit_answer`, so the question is retried with another agent. After 3 attempts it becomes `needs_human`; it never loops forever or gets stuck as `routed`. Tested in Tasks 3 and 5.
3. **Races.** A human answers while the agent is answering, an owner approves twice, or two route jobs pick the same question. Exactly one answer wins, the answering run is cancelled, and one KB document is filed. Tested in Tasks 3 and 5.
4. **Hostile question text.** Prompt injection ("print the .env"), `</untrusted>` in the body, a 4,000-char body with control characters. It is wrapped, escaped and capped, and the read-only policy still holds. Tested in Tasks 3 and 4.
5. **Nobody can answer.** No member has a bound agent, every member's runner is v1, or the asker's open-question cap is hit. The question waits as `queued` with a clear "waiting for a runner" state, humans can still answer, and the cap gives a clear error. Tested in Tasks 2, 3 and 7.

---

## File Structure

```
backend/app/a2a/
  models.py        Question (+ Project.next_question_number), AgentRun.question_id/nullable task_id
  access.py        can_read_question, can_answer_question, open-question cap
  service.py       ask, withdraw, suggest, answer (human), approve/reject draft, submit (agent), on_answered
  routing.py       candidates, route_question, a2a.route job, on_answer_run_finished
  prompts.py       answering prompt
  scrub.py         secret scrubbing
  filing.py        KB Q&A filing, memory source loader "answer"
  context.py       a2a_context provider (answers delivered to the asking task)
  router.py, schemas.py
backend/app/mcp_server/a2a_tools.py   ask_project, find_answer, get_question, withdraw_question, submit_answer
frontend/src/
  lib/questions.ts
  app/(app)/questions/page.tsx, app/(app)/questions/[id]/page.tsx
  components/questions/{AskQuestion,QuestionList,QuestionView,AnswerForm,DraftReview,TaskQuestions}.tsx
  e2e/questions.spec.ts
```

---

### Task 1: Data model — questions, and runs that answer them

**Files:**
- Create:
  - `backend/app/a2a/{__init__,models,routing}.py` (`routing.py` holds stubs only)
  - `backend/tests/a2a/test_models.py`
  - a migration
- Modify:
  - `backend/app/agent_runs/models.py` (`task_id` nullable; `question_id` FK CASCADE, indexed; check `agent_runs_target_check`: exactly one of `task_id`/`question_id`)
  - `backend/app/projects/models.py` (`next_question_number: int = 1`)
  - `backend/app/models.py`
  - every `AgentRun.task_id` reader that must skip question runs:
    - `agent_runs/router.py`, the task runs list (no change: it filters by task)
    - `agent_runs/service.py`: `_claim_next` (one active run per question too: a `question_running` sibling check like `task_running`), `_send_start`, `apply_update`, `finish_run`
    - `mcp_server/auth.py` (`require_run_task` refuses question runs with `wrong_task`)

**Interfaces:**
- Produces:
  - `QuestionStatus` enum (Global Constraints).
  - `Question{id, number, target_project_id, from_task_id, asked_by_user_id, asked_by_agent_id, title, body, context, status, answer_md|None, citations JSONB list, answer_source: "agent"|"human"|None, answered_by_user_id|None, answered_by_agent_id|None, draft_md|None, draft_citations JSONB, draft_agent_id|None, reject_reason|None (≤ 500), redacted: bool, tried_agent_ids JSONB list, attempts: int, kb_document_id|None (SET NULL), created_at, updated_at, answered_at|None}`.
    - Unique on (`target_project_id`, `number`).
    - Index on (`status`, `created_at`).
  - `AgentRun.question_id`.
- Run plumbing for question runs. Task 1 creates `app/a2a/routing.py` with stub bodies: `start_fields` fails the run with reason `not_supported`, and `on_answer_run_finished` does nothing. Task 3 replaces both bodies:
  - `_send_start` calls `a2a.routing.start_fields(db, run)` when `run.question_id` is set. It returns `(RunTask, local_path, v2 fields)`, or fails the run with `agent_not_bound`/`owner_lost_access` as for tasks.
  - `apply_update` ignores question runs (their progress is not stored). It still bumps `last_seq`.
  - `finish_run` calls `a2a.routing.on_answer_run_finished(db, run)` for question runs, instead of the task/workflow handling and `queue_extract("run")`.
  - `_claim_next` only claims question runs on runners that support `workflow/1`, as for workflow runs.

- [ ] **Step 1: Write failing tests:**
  - `test_run_needs_exactly_one_target` (neither → IntegrityError; both → IntegrityError)
  - `test_question_numbers_per_project` (two projects each start at 1)
  - `test_question_run_claim_one_active_per_question`
  - `test_question_run_not_claimed_on_v1_runner`
  - `test_question_run_updates_ignored_and_task_runs_unchanged` (run the existing agent_runs tests too)
  - `test_require_run_task_refuses_question_runs`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement. Generate the migration against `megoo_migrate`, name every new constraint, and check downgrade/upgrade. The downgrade deletes question runs before restoring NOT NULL.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(a2a): questions and question runs`.

### Task 2: Asking — REST, visibility, suggestions, withdraw

**Files:**
- Create:
  - `backend/app/a2a/{access,service,router,schemas}.py`
  - `backend/tests/a2a/test_ask.py`
- Modify: `backend/app/main.py`, `backend/app/tasks/schemas.py` and `backend/app/tasks/service.py` (`TaskOut.waiting_on: list[str]`)

**Interfaces:**
- Produces:
  - `async ask(db, user, *, project_key: str, body: str, title: str | None = None, context: str = "", task_key: str | None = None, agent_id: UUID | None = None) -> tuple[Question, list[Suggestion]]`
    - It validates as in Global Constraints. With `task_key`, the asker must have write access to that task (`get_task_for(write=True)`).
    - It numbers the question under a project row lock (`SELECT … FOR UPDATE` on the project, then increment `next_question_number`).
    - It records audit, publishes events, and enqueues `a2a.route`.
    - Viewers get 403 `forbidden`; an unknown project gives 404 `project_not_found`; the cap gives 429 `too_many_open_questions`.
  - `async suggest(db, user, project_id, text) -> list[Suggestion]` (Global Constraints).
  - `async withdraw(db, user, question) -> Question` is for the asker or an admin, while the question is open. It cancels an active answering run.
  - `can_read_question(db, user, q) -> bool` and `can_answer_question(db, user, q) -> bool` (Global Constraints).
  - Endpoints (`AuthedUser`):

    | Endpoint | Returns / does |
    |---|---|
    | `GET /api/questions/targets` | `[{key, name}]` |
    | `POST /api/questions/suggest {project_key, body}` | `[Suggestion]`; asks nothing |
    | `POST /api/questions {project_key, body, title?, context?, task_key?}` | 201 `{question: QuestionOut, suggestions}` |
    | `GET /api/questions?box=mine\|incoming&project=KEY&status=` | `mine`: asked by me; `incoming`: projects I can access, optionally one; newest first, limit 100 |
    | `GET /api/questions/{id}` | `QuestionOut`, or 404 when unreadable |
    | `POST /api/questions/{id}/withdraw` | withdraws the question |
    | `GET /api/tasks/{key}/questions` | questions asked from that task |

  - `QuestionOut{id, ref: "<TARGET>-Q<n>", target: {key, name}, title, body, context, status, answer_md, citations, answer_source, answered_by: {user, agent}, draft (only for those who may approve), redacted, attempts, from_task: {key, title}|None, asked_by: {user, agent}, kb_document_id, created_at, answered_at, can_answer, can_approve, can_withdraw}`.

- [ ] **Step 1: Write failing tests:**
  - `test_ask_numbers_and_audits_and_queues_route`
  - `test_title_defaults_to_first_line_and_limits` (body > 4,000 or context > 8,000 gives 422; NUL is stripped)
  - `test_viewer_cannot_ask_and_unknown_project_404`
  - `test_open_question_cap_429`
  - `test_visibility_matrix`:
    - target member yes; asker yes; asking-task project member yes; outsider 404 on GET and absent from lists
  - `test_suggestions_only_what_asker_can_read`:
    - the target project's KB doc is invisible to an outsider asker
    - a KB doc in the org space and an org memory conclusion are returned
  - `test_withdraw_by_asker_only_and_cancels_active_run`
  - `test_task_waiting_on_lists_targets_of_open_questions`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(a2a): ask a project, suggestions and visibility`.

### Task 3: Routing and the answering session

**Files:**
- Create:
  - `backend/app/a2a/{routing,prompts}.py`
  - `backend/tests/a2a/test_routing.py`
- Modify:
  - `backend/app/worker.py` (`HANDLER_MODULES` adds `app.a2a.routing`)
  - `backend/app/runner/router.py` (on hello, enqueue `a2a.route`)
  - `backend/app/main.py` (import `app.a2a.routing`, so its jobs register in the API process too)

**Interfaces:**
- Consumes: Task 1's run plumbing and Task 2's `Question`.
- Produces:
  - `prompts.ANSWER_PROMPT`, a fixed text covering Global Constraints' rules. It ends with: "When you are done, call submit_answer(answer_md, citations)."
  - `answer_prompt(q, target_key) -> str`: the prompt, then `## Question <TARGET>-Q<n>` and `wrap_untrusted("question", f"{title}\n\n{body}\n\nContext:\n{context}")`.
  - `async candidates(db, q) -> list[Agent]` (Global Constraints).
  - `async route_question(db, q) -> AgentRun | None` locks the question FOR UPDATE and only routes when it is `queued`.
  - Job `a2a.route` (periodic 60 s).
  - `async start_fields(db, run) -> tuple[RunTask, str, dict]` returns the synthetic task, the binding's `local_path`, and v2 fields with `role="answer"` and the MCP token.
  - `async on_answer_run_finished(db, run)`:
    - if the question already left `routed` (answered, draft or withdrawn), nothing happens;
    - otherwise apply the retry rule (Global Constraints) and enqueue `a2a.route`.

- [ ] **Step 1: Write failing tests:**
  - `test_route_picks_online_member_with_binding` (agent of a non-member skipped; agent without binding skipped; v1 runner skipped)
  - `test_route_prefers_least_busy_agent`
  - `test_no_candidate_stays_queued_and_routes_when_runner_says_hello`
  - `test_two_route_jobs_create_one_run` (concurrent `route_question` in two sessions)
  - `test_run_start_for_answer_is_read_only_with_synthetic_key_and_mcp` (fake runner socket from the Plan 2/3 test helpers; assert `role`, `policy`, `task.key == "PAY-Q1"`, `mcp.token` present, no files)
  - `test_answer_prompt_wraps_and_escapes_question` (`</untrusted>` in the body is escaped; the rules text is present)
  - `test_run_without_answer_retries_other_agent_then_needs_human_after_3`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(a2a): route questions to answering sessions`.

### Task 4: MCP tools — asking, answering, and answer-run scoping

**Files:**
- Create:
  - `backend/app/mcp_server/a2a_tools.py`, `backend/app/a2a/scrub.py`
  - `backend/tests/mcp/test_a2a_tools.py`, `backend/tests/a2a/test_scrub.py`
- Modify:
  - `backend/app/mcp_server/server.py`
  - `backend/app/mcp_server/kb_tools.py` and `backend/app/mcp_server/memory_tools.py` (answer runs may use the read tools)
  - `backend/app/mcp_server/workflow_tools.py`, so the task tools refuse answer runs
  - `backend/tests/mcp/test_mcp.py` (tool list)
  - methodology defaults `brainstorm.md`, `plan.md`, `build_implement.md` (one line naming `find_answer` and `ask_project`)

**Interfaces:**
- Produces:
  - Tools:

    | Tool | Returns / does | Who may use it |
    |---|---|---|
    | `find_answer(project_key, question)` | suggestions only | any token except answer runs |
    | `ask_project(project_key, question, context?, task_key?)` | `{question_id, ref, status, suggestions}`; a run token from a task run fills `task_key` with its task and refuses another task's key (`wrong_task`) | any token except answer runs |
    | `get_question(question_id)` | the visible `QuestionOut` subset (status, answer, citations) | any reader; an answer run sees its own question |
    | `withdraw_question(question_id)` | withdraws it | the asker |
    | `submit_answer(answer_md, citations)` | stores the answer | answer runs only, for their own question, only while `routed` and the run is running |

  - `scrub(text: str) -> tuple[str, bool]` (patterns in Global Constraints).
  - `async submit(db, run, answer_md, citations) -> Question` (in `a2a/service.py`) validates (Global Constraints), scrubs the answer and the citation paths, then applies the answer mode. Only the run's own question in `routed` is accepted; otherwise 409 `question_not_routed`.

- [ ] **Step 1: Write failing tests:**
  - `test_scrub_patterns` (each pattern redacted; ordinary text unchanged; returns `redacted` True only when changed)
  - `test_answer_run_tools_allowed_and_refused` (`get_question`, `submit_answer`, `kb_search`, `search_memory` allowed; `get_task`, `kb_write`, `ask_project`, `submit_design` give `not_allowed_in_role`)
  - `test_submit_answer_auto_mode_answers_and_scrubs` (an answer containing `AKIAABCDEFGHIJKLMNOP` is stored redacted; `redacted` is true; audit `a2a.answer.redacted`)
  - `test_submit_answer_manual_mode_creates_draft`
  - `test_submit_answer_other_question_or_after_run_ended_refused`
  - `test_ask_project_from_task_run_links_task_and_refuses_other_task`
  - `test_find_answer_returns_only_readable_suggestions`
  - `test_tool_list_includes_a2a_tools`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(mcp): ask other projects and answer their questions`.

### Task 5: Approve, reject, human answers — and what happens on an answer

**Files:**
- Create:
  - `backend/app/a2a/{filing,context}.py`
  - `backend/tests/a2a/test_answer.py`
- Modify:
  - `backend/app/a2a/service.py`, `backend/app/a2a/router.py`
  - `backend/app/memory/sources.py` (register the `"answer"` loader through `filing.py`)
  - `backend/app/main.py` (register `a2a_context` after the memory provider)

**Interfaces:**
- Produces:
  - `async approve(db, user, q, *, answer_md: str | None) -> Question` is for the draft agent's owner or an admin, while the status is `draft` (409 `not_a_draft` otherwise). It scrubs the edit.
  - `async reject(db, user, q, *, reason: str) -> Question` takes a reason of 1–500.
  - `async answer_by_human(db, user, q, *, answer_md: str, citations: list = []) -> Question`
  - `async on_answered(db, q)`:
    - files the KB document, queues memory extraction, delivers to the asking task, publishes, and audits;
    - is idempotent (a second call does nothing when `kb_document_id` is set);
    - its filing failure is logged and audited `a2a.filing_failed`, and never undoes the answer (savepoint, as in Plan 4).
  - Endpoints:

    | Endpoint | Error |
    |---|---|
    | `POST /api/questions/{id}/approve {answer_md?}` | |
    | `POST /api/questions/{id}/reject {reason}` | |
    | `POST /api/questions/{id}/answer {answer_md, citations?}` | 409 `already_answered` / `not_open` |

  - The memory source `"answer"` follows Global Constraints.
  - `async a2a_context(db, task, role) -> str | None` (Global Constraints). It skips `finish` and only includes questions the owner can read.

- [ ] **Step 1: Write failing tests:**
  - `test_approve_with_edit_by_owner_only_and_twice_409`
  - `test_reject_requeues_and_excludes_agent`
  - `test_human_answer_cancels_active_run_and_wins_race`: an agent `submit_answer` racing a human answer gives one answered state; the loser gets 409; one KB document.
  - `test_answer_filed_in_qa_folder_with_sources_and_author`
  - `test_answer_fed_to_memory_and_loader_scope`
  - `test_answer_delivered_to_asking_task_event_and_context` (the `## Answers from other projects` section with the answer inside `<untrusted source="answer">`)
  - `test_filing_failure_does_not_undo_answer`
  - `test_same_question_later_gets_suggestion_from_filed_answer` (A2A-6 / §11: ask again and the Q&A KB document is in the suggestions)
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(a2a): approve, answer, file and deliver`.

### Task 6: Frontend — questions

**Files:**
- Create:
  - `frontend/src/lib/questions.ts`
  - `frontend/src/app/(app)/questions/page.tsx`, `frontend/src/app/(app)/questions/[id]/page.tsx`
  - `frontend/src/components/questions/{AskQuestion,QuestionList,QuestionView,AnswerForm,DraftReview,TaskQuestions}.tsx` plus tests
- Modify:
  - `frontend/src/components/shell/Sidebar.tsx` ("Questions", Lucide `MessagesSquare`)
  - `frontend/src/components/task/TaskView.tsx` (a `TaskQuestions` section, and a "Waiting on PAY" badge from `waiting_on`)
  - `frontend/src/lib/realtime.ts` (`question.*` invalidates `["questions"]` and `["task"]`)
  - `frontend/src/lib/errors.ts` (`too_many_open_questions`, `question_not_routed`, `not_a_draft`, `already_answered`, `not_open`)
  - API types (`npm run gen:api`)

**Interfaces:**
- Produces:
  - `/questions` has three tabs: **Ask**, **My questions**, **Incoming**.
    - Ask: a project select from `/api/questions/targets`, the question, optional context, then a "Check for existing answers" step that shows suggestions with links. "Ask anyway" submits the question.
    - Incoming can be filtered by project and status. Drafts awaiting my approval come first.
  - `/questions/[id]`:
    - the question, its status line ("Waiting for a runner of PAY" | "Being answered by <agent>" | "Draft awaiting <owner>'s approval" | "Needs a human answer" | "Answered by …" | "Withdrawn")
    - the answer rendered with `Markdown` in `.kb-prose`, with citations as monospace `path:start-end`
    - a "Secrets were removed from this answer" notice when `redacted`
    - "View in Knowledge Base"
  - `AnswerForm` shows when `can_answer`. `DraftReview` shows when `can_approve`: an editable draft with Approve and with Reject (reason required). A Withdraw button shows when `can_withdraw`.
  - `TaskQuestions` lists a task's questions with status and links.

- [ ] **Step 1: Write failing tests:**
  - `AskQuestion shows suggestions before asking and asks anyway`
  - `QuestionView status lines for every status`
  - `QuestionView renders answer markdown, citations and redacted notice`
  - `DraftReview approve sends edit and reject requires reason`
  - `AnswerForm only when can_answer`
  - `TaskQuestions and waiting badge`
  - `question text renders without raw html`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm test`, `npx tsc --noEmit` and `npm run lint`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(frontend): agent-to-agent questions`.

### Task 7: End-to-end — a question answered across projects

**Files:**
- Create: `frontend/e2e/questions.spec.ts`
- Modify: `README.md` (Questions end-to-end test), and `frontend/e2e/helpers/runner.ts` only if a helper is missing

**Interfaces:**
- Consumes: the full stack (fake AI, the worker), the runner and the fake agent (Plan 3 helpers: `buildBinaries`, `startRunner`, `onPrompt`, `mcp`).

- [ ] **Step 1: Write the e2e** `questions.spec.ts` on a fresh stack. Projects `QAA` (the asker) and `QBB` (the target). The admin owns an agent bound to QBB in manual mode.
  1. With no runner running, ask QBB from task QAA-1 (via the UI). The question is `queued` ("Waiting for a runner of QBB"), and QAA-1 shows "Waiting on QBB".
  2. Start the runner. The fake agent's scenario matches the answer prompt and calls `submit_answer` with a citation and a fake AWS key in the text. The question becomes `draft`. Approve it in the UI with an edit. It becomes `answered`, the key shows as `[redacted]`, and there is a "Secrets were removed" notice.
  3. The answer is in QBB's KB under `Q&A/Q1: …` with a Sources section. QAA-1's thread shows "QBB answered Q1". Asking the same question again offers the Q&A document as a suggestion.
  4. A member of neither project gets 404 on the question. Through MCP with a personal token, `find_answer` returns the Q&A document for the admin.
  5. Ask another question, stop the runner, and answer it as a human from the Incoming tab: `answered` with `answer_source: human`.
- [ ] **Step 2:** Run it on the stack. Expected: FAIL until everything is wired.
- [ ] **Step 3:** Fix what it exposes, test-first in the owning module, as separate `fix(...)` commits.
- [ ] **Step 4:** Run `npx playwright test` (all specs) twice on fresh stacks, plus `uv run pytest -q`, `npm test` and `go test ./...`. Expected: PASS. Tear the stack down with `down -v` and touch only `megoo-e2e`.
- [ ] **Step 5:** Commit: `test(e2e): agent-to-agent questions end to end`.

---

## Spec coverage (Plan 6)

| BRD item | Task |
|---|---|
| A2A-1 ask a project, with context | 2, 4, 6 |
| A2A-2 route to an online member's runner with the repository | 3 |
| A2A-3 read-only answering session citing files and lines | 3, 4 |
| A2A-4 manual (approve with edit) and auto modes | 4, 5, 6 |
| A2A-5 queued when no runner; "waiting on" state; humans answer | 2, 3, 5, 6 |
| A2A-6 filed in the KB Q&A section and fed to memory; check KB/memory first | 2, 5 |
| A2A-7 untrusted input; no secrets; read-only; visible to target members | 2, 3, 4 |
| KB-4 agent-to-agent Q&A filed | 5 |
| MEM-2 agent-to-agent Q&A as memory input | 5 |
| AGT-31 ask another project's agents | 4 |
| §8 worker question routing | 3 |
| §11 success criteria 4/5 | 5, 7 |
