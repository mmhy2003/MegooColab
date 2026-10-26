# MegooColab Plan 5 — Collective Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Honcho-style collective memory. A background worker reads what people and agents write and records short, sourced **conclusions** about entities: the organization, teams, projects, people, agents and products. A nightly **dreaming** run consolidates them: it replaces outdated ones, deduces, induces and links premises, and refreshes one **summary card** per entity. People and agents can **ask the memory**, and get answers that cite the conclusions used. Stage prompts carry relevant memory. Humans can browse, correct, delete and pin conclusions, and anything deleted or corrected is never re-derived from the same source.

**Architecture:**
- **Backend:** a new `memory` module.
  - Conclusions are scoped like the Knowledge Base: organization, team or project, taken from their source. Every read filters by the caller's current access.
  - Learning runs in the Plan 4 job queue and worker. The jobs are `mem.extract` per source, `mem.dream`, `mem.dream_tick` (hourly) and `mem.reconcile`.
  - The AI gateway gains `complete()` for LLM jobs (extraction, dreaming, answering). It is metered like `embed()`, and in fake mode it uses deterministic local fakes.
  - Retrieval reuses the Plan 4 hybrid recipe: full-text plus pgvector with a distance cut-off, fused by reciprocal rank (RRF).
- **Frontend:** a Memory area with an Ask box, an entity browser, entity pages (summary cards, conclusions, sources, reasoning chains, correct/delete/pin) and products. The admin AI page gains the new jobs and a Dreaming panel.
- **Runner:** unchanged.

**Tech Stack:** Plans 1–4 stack. No new dependencies; LLM calls go through `litellm.acompletion` (already installed: `litellm==1.106.4`).

**Spec:** [docs/brd.md](../../brd.md). This plan covers:
- §6.8 MEM-1 to MEM-10
- AGT-31 "ask/search memory"
- WF-4 "relevant memory … context"
- ADM-2 "memory deletions" audited
- the §5 permissions row "Correct / delete memory conclusions"
- R4 (sources, reasoning chain, human correction, confidence)

Agent-to-agent Q&A as a memory input (A2A-6) arrives with Plan 6. This plan gives it the source hook it needs.

**Builds on:** Plans 1–4 on `main`. Reuse:
- `app/jobs/queue` (`enqueue`, `register`, `register_periodic`, `PERIODIC`) and the worker's `HANDLER_MODULES` (`app/worker.py`)
- `app/ai/client` (`embed`, `current_model`, `configured_model`, `AiNotConfigured`, fake mode, `_record`)
- the `_embeddings_settings_changed` hook in `app/ai/router.py`
- KB `access.readable_space_ids` as the model for scope reads; `search.SEMANTIC_MAX_DISTANCE`, `STOPWORDS` and the RRF code style
- `app/workflow/context.py`: `context_providers`, `wrap_untrusted`, `_escape`, and `_provided` (providers are isolated, and dropped first when a prompt is too long)
- MCP `tool_session`, `current_run` and the `KB_TOOL_ROLES` pattern
- `audit.record`, `NoNulStr`, `Event`/`publish`
- frontend `api`, `errorMessage`, `KbMarkdown`, `.kb-prose`, `useMe`

## Global Constraints

**Entities (MEM-1)**
- `MemEntity{id, kind: org|team|project|user|agent|product, ref_id|None, name, description, created_at}`.
- `ref_id` is the team, project, user or agent id. It is null for `org` and `product`.
- Unique on (`kind`, `ref_id`). There is exactly one `org` entity.
- Entities for teams, projects, users and agents are created lazily: `ensure_entity(db, kind, ref_id)`, plus a startup `ensure_core_entities()` for org, teams and projects. They cascade-delete with their team, project or agent. A user's entity stays when the user is deactivated.
- Products are created, renamed and deleted by admins and managers. Product fields: `name` 1–100 chars, `description` ≤ 2,000, and an optional list of project ids they relate to.

**Scopes and access (MEM-7)**

Every conclusion and card has a scope, `scope_kind ∈ {org, team, project}` plus `scope_team_id` or `scope_project_id`. The foreign keys are ON DELETE CASCADE.

| Source | Scope |
|---|---|
| Task thread: title, description, comments | the task's project |
| Agent run metadata | the run's task's project |
| Review findings | the task's project |
| KB document | its space (org, team or project) |
| Human correction | the corrected conclusion's scope |
| Derived (dreaming) | the scope of its premises; premises are never mixed across scopes |

- **Readable scopes:** `org`, the user's teams, and `accessible_project_ids(user)`. Admins can read everything.
- Every list, search, answer, card, MCP result and prompt context filters on the caller's readable scopes **at read time**. Anything outside them is reported as not found (404 / `not_found`).
- **Who may correct, delete or pin:**

  | Role | Scopes |
  |---|---|
  | admin | any scope |
  | manager | any scope they can read |
  | member | `project` scopes they can read, and `team` scopes of their own teams |
  | viewer | none |

  Anyone without the right gets 403 when they can read the scope, and 404 when they cannot.

**Conclusions (MEM-3, MEM-8)**
- Fields:
  - `text` 1–500 chars (`NoNulStr`)
  - `kind`: `observed` | `deduced` | `induced` | `correction`
  - `confidence` 0–1; required for `induced`, null otherwise
  - `status`: `active` | `superseded` | `deleted`
  - `pinned` bool
  - `source_kind` | None, `source_id` | None, `source_label` (≤ 200)
  - `entity_id`
  - `embedding` | None, `embedding_model` | None
  - a generated `search_tsv` (`simple` config, from `text`)
  - `superseded_by_id` | None, `created_by_user_id` | None, `created_at`, `updated_at`
- Source kinds: `task` (title and description), `comment`, `run`, `review`, `kb_document`, `answer`. `answer` is reserved for Plan 6.
- Reasoning chain: `MemPremise(conclusion_id, premise_id)`, where premise ≠ conclusion. A chain is shown to a depth of 5.
- **Suppression:**
  - Deleting a conclusion, or correcting it, records a `MemSuppression{source_kind, source_id, entity_id, text, embedding|None}`.
  - Extraction drops a candidate when it has the same source and entity as a suppression, and either its normalized text matches (lowercase, whitespace collapsed) or its cosine distance to the suppression's embedding is ≤ 0.2.
  - Suppressions are kept forever.
- Pinned conclusions are never superseded, by re-extraction or by dreaming.
- Deleting is soft (`status = deleted`) and audited as `memory.conclusion.deleted`. Correcting is audited as `memory.conclusion.corrected`.

**Learning (MEM-2, MEM-3)**
- Each source change enqueues `mem.extract` with `{source_kind, source_id}`, `dedupe_key = "mem.extract:<kind>:<id>"` and `run_after = now + 60 s` (to batch quick edits).
- Hooks:
  - a comment is created or edited
  - a task is created, or its title or description changes
  - a run finishes (any outcome)
  - a review is submitted
  - a KB document is created, updated or moved
- **Source text** sent to the model is capped at 12,000 chars:

  | Source | Text |
  |---|---|
  | `run` | the run summary, plus the run's `agent_message` event texts (newest first, within the cap) |
  | `review` | each finding as `severity file:line summary`, plus the verdict |
  | `task` | title and description |
  | `comment` | body |
  | `kb_document` | title and body |

  It never includes file contents or diffs. NFR-2: the runner already strips them.
- **Candidate entities** offered to the model, in this order (so `E1` is always the scope's own entity):
  - the scope's own entity: the project, the team, or the org
  - org, when it is not already `E1`
  - for a project scope, the project's teams
  - for task, comment, run or review sources: the task's assignee (user or agent), the comment author, the run's agent and its owner
  - products linked to the project
  - every product whose name appears in the text (case-insensitive)

  Each is given as `E1…En` with its kind and name. The model may only attach conclusions to these ids; anything else is dropped.
- At most 10 conclusions per extraction. Re-extracting a changed source marks that source's previous **unpinned observed** conclusions `superseded` before inserting the new ones. A source that is unchanged since its last extraction is skipped; the hash of the extracted text is kept in `MemSourceState{source_kind, source_id, text_hash, extracted_at}`.
- New conclusions are embedded with the embeddings job model. If embeddings are not configured, they are stored without a vector. `mem.reconcile` (periodic, every 1,800 s, and enqueued with `kb.reconcile` whenever embeddings settings change) embeds conclusions that lack a vector from the current model.

**Dreaming (MEM-4)**
- `mem.dream_tick` runs every 3,600 s (`queue.register_periodic`). It enqueues `mem.dream {trigger: "scheduled"}` (dedupe `"mem.dream"`) when the current UTC hour equals `settings.memory_dream_hour_utc` (default `3`) and no dream run started in the last 20 h.
- Admins trigger `POST /api/admin/memory/dream` → `{trigger: "manual"}`.
- A dream run (`MemDreamRun{id, trigger, status: running|done|failed, started_at, finished_at, stats JSONB, error ≤ 500}`) goes through each (entity, scope) pair that has an active conclusion created or changed since that pair's last card refresh. The first run covers every pair.
- For each pair, the dreaming model receives:
  - up to 200 active conclusions, as `C1…Cn` with kind, confidence, pinned flag and date
  - the current card

  It returns JSON:
  ```
  {replace: [{ids, text}], deduce: [{premises, text}], induce: [{premises, text, confidence}], card}
  ```
- Validation:
  - Ids must be among those provided.
  - A `replace` never targets a pinned conclusion. It marks the targets `superseded` and points them at the new conclusion, which is `kind = deduced` with those targets as premises.
  - `induce` needs at least 2 premises and a confidence in [0, 1].
  - Each list holds at most 20 items. Texts and the card are clipped to their limits.
  - Invalid items are dropped one by one, never the whole response.
- Cards: `MemCard{entity_id, scope_kind, scope ids, summary_md ≤ 2,000, conclusion_ids JSONB, refreshed_at}`, unique per (entity, scope).

**Answering (MEM-5)**
- `answer(db, user, question, *, project_id=None)`:
  1. Retrieve the top 20 readable conclusions with a hybrid search over the question (any-word full-text with stopwords removed, plus vectors with the cut-off), and the readable cards of the entities those conclusions belong to.
  2. Call the answering model with that list as `C1…Cn` and the cards.
  3. Return `{answer_md ≤ 8,000, cited: [conclusion]}`. The cited ids must be among those provided; others are dropped.
- With no readable conclusions it answers "The memory has nothing on that yet." without calling the model.
- The question is 1–1,000 chars.

**Prompt context (MEM-6)**
- The memory context provider adds `## Memory`. Within 6,000 chars it includes:
  - the readable cards for the task's project, its teams and the org (in that order)
  - the top 10 readable conclusions from a hybrid search over the task title and the first 1,000 chars of the description

  Every block is wrapped `<untrusted source="memory">`. It skips the `finish` role and uses the agent owner's access, as the KB provider does.

**AI jobs (MEM-10)**
- `JOBS = ("embeddings", "extraction", "dreaming", "answering")`.
- `complete(db, job, messages, *, timeout=120, max_tokens=2000) -> str` asks for JSON (`response_format={"type": "json_object"}`). It records usage (`prompt_tokens`, `completion_tokens`, cost), like `embed`.
- Fake mode: `FAKE_COMPLETIONS: dict[str, Callable[[list[dict]], str]]` registered by the memory module. It is deterministic and makes no network call.
- Exact prompts live in `app/memory/prompts.py`. Every input text from people or agents goes inside `<untrusted>`.

**Untrusted content (NFR-3):** conclusions, cards and answers are model output derived from untrusted text. They render with the shared `Markdown` component (no raw HTML), and every prompt wraps them as untrusted.

## Review Focus

1. **Access leaks through derived knowledge.** A conclusion, card, answer, citation, context excerpt or MCP result must never carry anything from a scope the caller cannot read now. This includes dreaming output, which must never combine premises from different scopes, and cards for people and agents who work across projects. Tested in Tasks 2, 5, 6, 7, 9 and 10.
2. **Re-derivation after a human deleted or corrected something.** The same source re-extracted after an edit, a near-duplicate wording, or dreaming re-deducing the deleted fact must not bring a deleted or corrected conclusion back from that source. Tested in Tasks 4, 7 and 8.
3. **The model returns garbage.** Non-JSON, unknown ids, inductions with one premise, replace targets that are pinned or already deleted, over-long text, or more than the cap. Each bad item is dropped, never the whole job, and a fully unparseable reply fails the job visibly. Tested in Tasks 1, 4 and 7.
4. **The provider is missing, failing or slow.** Without an extraction model, nothing is extracted, nothing breaks, and the admin sees "not configured". A failing provider gives retries, then a visible failed job. Ask the memory says so instead of hanging (60 s cap). Prompt context degrades to nothing. Tested in Tasks 1, 4, 6 and 9.
5. **Volume and churn.** A comment edited ten times within a minute gives one extraction. A huge KB document is capped at 12,000 chars of input. An unchanged source is not re-sent to the model. A dream run with nothing new costs no model calls. Tested in Tasks 3, 4 and 7.

---

## File Structure

```
backend/app/
  ai/client.py                 + complete(), JOBS, FAKE_COMPLETIONS, AiBadOutput, parse_json()
  memory/models.py             MemEntity, MemConclusion, MemPremise, MemSuppression, MemCard, MemSourceState,
                               MemDreamRun, MemProductProject
  memory/access.py             readable scopes, can_edit, scope filters
  memory/entities.py           ensure_entity, ensure_core_entities, products
  memory/sources.py            SOURCE_LOADERS, load_source(), hooks: queue_extract()
  memory/prompts.py            extraction / dreaming / answering prompts
  memory/fakes.py              deterministic fake completions (fake mode)
  memory/extract.py            mem.extract handler, suppression check, embedding, mem.reconcile
  memory/search.py             search_conclusions (hybrid, scoped)
  memory/answer.py             answer()
  memory/dream.py              mem.dream, mem.dream_tick
  memory/context.py            memory context provider
  memory/router.py, schemas.py REST
  mcp_server/memory_tools.py   ask_memory, search_memory
frontend/src/
  lib/memory.ts                hooks, keys, types
  app/(app)/memory/page.tsx                 ask + entities + products
  app/(app)/memory/entity/[id]/page.tsx     entity page
  components/memory/{AskMemory,EntityList,ConclusionList,ConclusionItem,ReasoningChain,ProductEditor,DreamPanel}.tsx
  e2e/memory.spec.ts
```

---

### Task 1: AI gateway — LLM completions for the memory jobs

**Files:**
- Modify: `backend/app/ai/client.py`, `backend/app/ai/router.py` (job list; reindex hook)
- Create: `backend/tests/ai/test_complete.py`

**Interfaces:**
- Produces:
  - `JOBS = ("embeddings", "extraction", "dreaming", "answering")`, which the admin GET/PUT `/api/admin/ai/jobs` lists and accepts.
  - `async complete(db, job: str, messages: list[dict], *, timeout: float = 120, max_tokens: int = 2000) -> str`
    - It resolves the job's provider and model like `embed`, and calls `litellm.acompletion(model=…, messages=…, api_key=…, api_base=…, timeout=…, max_tokens=…, response_format={"type": "json_object"})`.
    - It returns `choices[0].message.content` and records `AiUsage(job, model, input_tokens=prompt_tokens, output_tokens=completion_tokens, cost)`. On failure it records `ok=False` and re-raises.
    - It raises `AiNotConfigured` when the job has no model.
    - In fake mode it returns `FAKE_COMPLETIONS[job](messages)`, or raises `AiNotConfigured` when no fake is registered. It records usage with cost 0.
  - `FAKE_COMPLETIONS: dict[str, Callable[[list[dict]], str]] = {}`
  - `class AiBadOutput(Exception)`
  - `parse_json(text: str, model: type[BaseModel]) -> BaseModel` strips a leading ```` ```json ```` fence and validates. On any failure it raises `AiBadOutput` with the first 200 chars.
  - `POST /api/admin/ai/jobs/{job}/test` for an LLM job sends one tiny prompt (`[{"role": "user", "content": "Reply with {\"ok\": true}"}]`). Its response shape is unchanged.
  - Reindex hook: `ai.REINDEX_JOBS: list[str] = ["kb.reconcile"]`. `_embeddings_settings_changed` enqueues every kind in it (deduped) when the model name is unchanged; on a model change it still enqueues `kb.reembed_all`. Task 4 appends `"mem.reconcile"`.

- [ ] **Step 1: Write failing tests:**
  - `test_jobs_list_includes_llm_jobs` (GET lists all four in order)
  - `test_complete_calls_litellm_and_records_usage`: monkeypatch `litellm.acompletion` to return `SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"a":1}'))], usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3))`. Assert the returned text, `response_format` passed, and a usage row `(job="extraction", input_tokens=7, output_tokens=3, ok=True)`.
  - `test_complete_failure_recorded_and_raised`
  - `test_complete_not_configured_raises`
  - `test_complete_fake_mode_uses_registered_fake_and_raises_without_one`
  - `test_parse_json_strips_fence_and_rejects_garbage` (```` ```json\n{…}\n``` ```` parses; `"not json"` and a schema mismatch raise `AiBadOutput`)
  - `test_test_endpoint_llm_job` (fake mode with a registered fake returns ok)
  - `test_settings_change_enqueues_every_reindex_job` (append a test kind to `REINDEX_JOBS`; saving the same model queues both)
- [ ] **Step 2:** Run `uv run pytest tests/ai -q`. Expected: FAIL.
- [ ] **Step 3:** Implement. Check `litellm.acompletion`'s `response_format`, usage fields and cost for chat completions with Context7 (`/berriai/litellm`) first.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(ai): llm completions for memory jobs`.

### Task 2: Memory data model, entities and access

**Files:**
- Create:
  - `backend/app/memory/{__init__,models,access,entities}.py`
  - `backend/tests/memory/test_access.py`
  - a migration
- Modify:
  - `backend/app/models.py`
  - `backend/app/main.py` (`ensure_core_entities` at startup, next to `ensure_spaces`)
  - `backend/app/teams/router.py`, `backend/app/projects/router.py` (create entities beside the KB spaces)

**Interfaces:**
- Produces:
  - Models as in Global Constraints, plus:
    - `MemProductProject(product_entity_id, project_id)`, both CASCADE, primary key on both.
    - `MemConclusion` has a check constraint: exactly one of the scope ids set, matching `scope_kind` (none for `org`).
    - `search_tsv` is generated: `to_tsvector('simple', text)`, with a GIN index.
    - Indexes on (`entity_id`, `status`), (`source_kind`, `source_id`), (`scope_project_id`), (`scope_team_id`).
    - `MemSuppression` has an index on (`source_kind`, `source_id`, `entity_id`).
    - All constraints are named. Generate the migration against `megoo_migrate`.
  - `Scope = tuple[Literal["org","team","project"], uuid.UUID | None]`
  - `async readable_scopes(db, user) -> ReadableScopes`, a dataclass `{all: bool, team_ids: set, project_ids: set}`, with `.clause(model)` returning a SQLAlchemy filter on a model that has the scope columns.
  - `async can_read_scope(db, user, scope) -> bool`
  - `async can_edit_scope(db, user, scope) -> bool` (the permission table above)
  - `async ensure_entity(db, kind, ref_id) -> MemEntity`: get or create, with `name` taken from the referenced row (team name, project `KEY — name`, user name, agent name, "Organization").
  - `async ensure_core_entities(db)`
  - `async org_entity(db) -> MemEntity`
  - `async create_product(db, user, name, description, project_ids) -> MemEntity`, `update_product(...)`, `delete_product(...)`. Admins and managers only (403 otherwise); a manager may link only projects they can read.

- [ ] **Step 1: Write failing tests:**
  - `test_core_entities_created_once`
  - `test_entity_names_from_rows`
  - `test_readable_scopes_matrix` (org for all; team for its members; project for project members; admin all; a user who loses team membership loses the team and project scopes)
  - `test_can_edit_scope_matrix`, matching the permission table:
    - a member can edit project scopes they can read and their own team scopes, but not org
    - a manager can edit anything readable; an admin anything
    - a viewer nothing
  - `test_conclusion_scope_check_constraint` (an org scope with a project id is rejected)
  - `test_scope_rows_cascade_with_project`
  - `test_products_admin_manager_only_and_project_links_checked`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement. Check `downgrade -1` and `upgrade head` on `megoo_migrate`.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(memory): entities, conclusions, scopes and access`.

### Task 3: Sources and learning hooks

**Files:**
- Create: `backend/app/memory/sources.py`, `backend/tests/memory/test_sources.py`
- Modify:
  - `backend/app/tasks/activity.py` (comment create and edit)
  - `backend/app/tasks/service.py` (`create_task`, and `update_task` when the title or description changed)
  - `backend/app/agent_runs/service.py` (`finish_run`)
  - `backend/app/workflow/build.py` (`submit_review`)
  - `backend/app/kb/service.py` (`create_document`, `update_document`, `move_document`)

**Interfaces:**
- Produces:
  - `SourceKind = Literal["task", "comment", "run", "review", "kb_document", "answer"]`
  - `@dataclass Source{kind, id, scope: Scope, text: str (≤ 12,000), label: str (≤ 200), link: str, candidates: list[MemEntity]}`
    - `link` is the frontend path: `/projects/<KEY>/tasks/<n>` for task sources, `/kb/doc/<id>` for KB sources.
  - `async load_source(db, kind, id) -> Source | None` returns None when the source is gone, or when its text is empty after trimming.
  - `SOURCE_LOADERS: dict[str, Callable]`. Plan 6 adds `"answer"`.
  - `async queue_extract(db, kind, id)` enqueues `mem.extract` with dedupe and `run_after = now + 60 s` (Global Constraints).
- Text assembly and candidate rules are exactly as in Global Constraints. Product name matching is case-insensitive and whole-word.

- [ ] **Step 1: Write failing tests:**
  - `test_each_hook_queues_one_deduped_extract` (comment create plus two edits within the window give one queued `mem.extract:comment:<id>`; task create; a title edit; a description-only edit; a status-only edit queues nothing; run finish; review submit; KB create, update and move)
  - `test_load_source_text_and_scope_per_kind` (task, comment and review are project-scoped; a KB doc in a team space is team-scoped; the run text contains the summary and the agent messages and never a `file_change` path)
  - `test_source_text_capped_12000`
  - `test_candidates_include_people_agents_products` (a product named "Atlas", linked or mentioned, is offered)
  - `test_missing_source_returns_none`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement. Each hook is one `await queue_extract(...)` call inside the existing transaction.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(memory): sources and learning hooks`.

### Task 4: Extraction, suppression and embedding

**Files:**
- Create:
  - `backend/app/memory/{prompts,fakes,extract}.py`
  - `backend/tests/memory/test_extract.py`
- Modify:
  - `backend/app/worker.py` (`HANDLER_MODULES` adds `app.memory.extract` and `app.memory.dream`)
  - `backend/app/main.py` (import `app.memory.fakes`, which registers fakes only when `settings.ai_fake`)
  - `ai.REINDEX_JOBS` gains `"mem.reconcile"`, appended when `app/memory/extract.py` is imported

**Interfaces:**
- Consumes: `load_source`, `complete`, `parse_json`, `embed`, `ensure_entity`.
- Produces:
  - `prompts.EXTRACTION_SYSTEM`. The user message holds the candidate list and the source text inside `<untrusted source="<kind>">` with `_escape`. It asks for:
    ```
    {"conclusions": [{"entity": "E<n>", "text": "<one self-contained fact, ≤ 300 chars>"}]}
    ```
    covering durable facts about goals, decisions, conventions, ownership, constraints and preferences, and excluding transient status.
  - `class ExtractionOut(BaseModel)`: `conclusions: list[{entity: str, text: str}]` (unbounded on parse; capped after).
  - Job `mem.extract(payload {source_kind, source_id})`:
    1. Load the source; if None, do nothing.
    2. If its `text_hash` equals `MemSourceState`'s, do nothing.
    3. Otherwise call `complete(job="extraction")`.
       - `AiNotConfigured`: complete with no change and leave the state unhashed, so it is extracted once the job is configured.
       - `AiBadOutput` or a provider error: re-raise, so the job retries.
    4. Keep at most 10 items whose entity is a known candidate and whose text is 1–500 chars after trimming.
    5. Drop suppressed candidates (Global Constraints).
    6. Mark the source's earlier unpinned `observed` conclusions `superseded`.
    7. Insert the new ones with the source's scope, `source_label` and `kind = observed`, and embed them (on `AiNotConfigured`, store without vectors).
    8. Upsert `MemSourceState`.
  - `fakes.fake_extraction(messages) -> str`: deterministic. Every sentence (split on `.`, `!`, `?`, newline) with at least 4 words, up to 5 of them, is attached to `E1`.
  - `fakes.fake_dreaming` and `fakes.fake_answering` are defined in Tasks 7 and 6.
  - Job `mem.reconcile` (periodic every 1,800 s, and in `REINDEX_JOBS`) embeds up to 1,000 active conclusions lacking a current-model vector, in batches of 64.

- [ ] **Step 1: Write failing tests** (fake mode unless noted):
  - `test_extract_creates_sourced_scoped_conclusions` (a comment on PAY gives conclusions on the PAY project entity, scope project PAY, `source_kind = "comment"`, with an embedding of the fake model)
  - `test_unchanged_source_not_resent` (count fake calls)
  - `test_edit_supersedes_previous_unpinned_but_keeps_pinned`
  - `test_deleted_conclusion_not_rederived_from_same_source`: delete one, then edit the source with a near-identical sentence ("The API uses HMAC signatures" vs "the API uses  HMAC signatures!"). It is not re-created. A different source with the same fact does create it.
  - `test_corrected_conclusion_not_rederived`
  - `test_bad_items_dropped_and_garbage_fails_job`: the fake returns an unknown entity id, a 600-char text and 12 items, so only valid items are kept and at most 10. A fake returning `"nope"` fails the job with `last_error` containing `AiBadOutput`.
  - `test_not_configured_extracts_nothing_and_retries_later` (real mode, no model: no conclusions, no state; after configuring and re-running, extracted)
  - `test_extraction_prompt_wraps_untrusted` (source text with `</untrusted>` is escaped in the messages passed to `complete`)
  - `test_reconcile_embeds_missing_vectors`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(memory): conclusion extraction`.

### Task 5: Scoped hybrid retrieval

**Files:**
- Create: `backend/app/memory/search.py`, `backend/tests/memory/test_search.py`

**Interfaces:**
- Consumes: `readable_scopes`, `ai.embed`, `ai.current_model`, KB `search.STOPWORDS`, `SEMANTIC_MAX_DISTANCE`, `QUERY_TIMEOUT_SECONDS`.
- Produces `async search_conclusions(db, user, query: str, *, entity_ids: set[UUID] | None = None, project_id: UUID | None = None, limit: int = 20, match_any: bool = True) -> list[MemConclusion]`:
  - Active conclusions only, within readable scopes, optionally restricted to the given entities or to scopes relevant to one project (that project, its teams, org).
  - Full-text with any-word matching (stopwords and words of 2 letters or fewer removed).
  - Semantic with the cut-off and a 5 s query timeout; on a provider error it falls back to full-text.
  - Fused with RRF k=60. Pinned conclusions get +0.01.
  - An empty query or empty scope gives `[]`.

- [ ] **Step 1: Write failing tests:**
  - `test_search_respects_scopes_now` (remove the user from the team, and the project's conclusions vanish)
  - `test_search_excludes_deleted_and_superseded`
  - `test_pinned_ranks_first_among_equals`
  - `test_project_filter_includes_org_and_team_scopes`
  - `test_unrelated_query_returns_nothing` (fake vectors; distance cut-off)
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(memory): scoped hybrid retrieval`.

### Task 6: Ask the memory

**Files:**
- Create: `backend/app/memory/answer.py`, `backend/tests/memory/test_answer.py`
- Modify: `backend/app/memory/prompts.py`, `backend/app/memory/fakes.py`

**Interfaces:**
- Produces:
  - `prompts.ANSWERING_SYSTEM`. The user message holds the question, then the cards and conclusions as `C<n>` inside `<untrusted source="memory">`. It asks for `{"answer": "<markdown>", "cited": ["C<n>", …]}`, citing only what was used, and saying plainly when the memory does not know.
  - `async answer(db, user, question: str, *, project_id: UUID | None = None) -> AnswerResult{answer_md: str, cited: list[MemConclusion]}`
    - It uses `complete(job="answering", timeout=60)`.
    - When there are no readable conclusions, it returns the fixed text from Global Constraints without calling the model.
    - On `AiNotConfigured` it raises HTTP 409 `memory_answering_not_configured`.
    - On a provider error, timeout or `AiBadOutput` it raises HTTP 502 `memory_unavailable`.
    - Cited ids outside the provided list are dropped. `answer_md` is clipped to 8,000.
  - `fakes.fake_answering(messages)` returns `{"answer": "From memory: <first conclusion text>", "cited": ["C1"]}`, or `{"answer": "I don't know.", "cited": []}` when there is none.

- [ ] **Step 1: Write failing tests:**
  - `test_answer_cites_only_provided_readable_conclusions` (the fake cites C1 and "C99", so only C1 is returned; the conclusion text is in the answer)
  - `test_answer_never_sees_unreadable_scopes` (assert on the messages passed to `complete`)
  - `test_empty_memory_answer_without_model_call`
  - `test_not_configured_409_and_provider_error_502`
  - `test_question_and_answer_untrusted_wrapping`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(memory): ask the memory`.

### Task 7: Dreaming — consolidation, reasoning chains and summary cards

**Files:**
- Create: `backend/app/memory/dream.py`, `backend/tests/memory/test_dream.py`
- Modify:
  - `backend/app/memory/prompts.py`, `backend/app/memory/fakes.py`
  - `backend/app/core/config.py` (`memory_dream_hour_utc: int = 3`)

**Interfaces:**
- Produces:
  - `prompts.DREAMING_SYSTEM` (output as in Global Constraints).
  - `class DreamOut(BaseModel)`
  - Job `mem.dream(payload {trigger, run_id?})`:
    - Creates or uses a `MemDreamRun`.
    - Iterates (entity, scope) pairs with changes since their card's `refreshed_at` (all pairs when there is no card). Only active conclusions of that one scope are sent, so premises are never mixed across scopes.
    - Applies the validated operations (Global Constraints), writing `MemPremise` rows for `replace` (premises = the replaced ids), `deduce` and `induce`.
    - Upserts the card with `conclusion_ids` = every id provided.
    - Sets `stats {pairs, replaced, deduced, induced, cards, dropped}`, `done` or `failed` with the error.
    - A pair whose model call fails counts in `stats.failed_pairs`; the run continues with the next pair.
    - Before deducing or inducing, it checks a new text against the suppressions of its premises' sources. Suppressed texts are dropped, so dreaming does not re-derive a deleted fact.
  - Job `mem.dream_tick` (periodic 3,600 s): the schedule rule from Global Constraints.
  - `fakes.fake_dreaming(messages)` is deterministic:
    - exact duplicate texts → `replace` with the first text
    - every pair of conclusions sharing a word of 6+ letters → one `induce` with premises [both], confidence 0.6, text `"Pattern: <word>"`
    - card = the first three texts joined by `"; "`
  - `async start_dream(db, user) -> MemDreamRun` (admin) creates a run with `trigger = manual` and enqueues `mem.dream {run_id}`. It gives 409 `dream_running` while one is running.

- [ ] **Step 1: Write failing tests:**
  - `test_dream_replaces_duplicates_and_links_premises`
  - `test_induction_needs_two_premises_and_confidence` (the fake is patched to return a 1-premise induction and confidence 1.5; both are dropped and `stats.dropped` is 2)
  - `test_pinned_never_replaced`
  - `test_dream_never_mixes_scopes` (identical texts in project A and project B are not merged; each scope gets its own card)
  - `test_cards_per_entity_and_scope_and_nothing_new_no_calls`
  - `test_dream_does_not_rederive_deleted`
  - `test_tick_enqueues_only_at_dream_hour_once_per_20h` (freeze time with an injectable `now`)
  - `test_manual_dream_admin_only_and_409_when_running`
  - `test_failed_pair_does_not_abort_run`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(memory): dreaming`.

### Task 8: Memory REST API — browse, correct, delete, pin, products, dreaming

**Files:**
- Create: `backend/app/memory/{router,schemas}.py`, `backend/tests/memory/test_api.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Endpoints (`AuthedUser` unless noted):
  - `GET /api/memory/entities?kind=&q=` returns `[{id, kind, name, conclusion_count}]`. It lists:
    - org
    - teams the caller belongs to, and projects they can access
    - every user and agent, products
    - and only counts readable active conclusions; admins see all teams and projects.
  - `GET /api/memory/entities/{id}` returns `{entity, cards: [{scope, summary_md, refreshed_at}], products?: [project refs]}` with readable cards only. An unreadable team or project entity gives 404.
  - `GET /api/memory/entities/{id}/conclusions?status=active|superseded|deleted|all&cursor=&limit=50` returns readable conclusions, newest first, with keyset paging:
    ```
    {items: [ConclusionOut], next_cursor}
    ```
    `ConclusionOut` is `{id, text, kind, confidence, status, pinned, scope: {kind, id, name}, source: {kind, label, link}|null, created_at, can_edit}`.
  - `GET /api/memory/conclusions/{id}` returns `{conclusion, premises: tree to depth 5, derived: [conclusions using it as a premise]}`. Premises and derived items outside readable scopes are omitted. They can only be from the same scope, so this is defence in depth.
  - `POST /api/memory/conclusions/{id}/correct {text}`:
    - creates a new `kind = correction` conclusion (same entity and scope, `created_by_user_id`, premise = the old one)
    - marks the old one `superseded`, with `superseded_by` the new one
    - adds a suppression for the old one's source
    - returns the new one
  - `DELETE /api/memory/conclusions/{id}` → status `deleted`, plus a suppression and an audit entry `memory.conclusion.deleted`.
  - `POST /api/memory/conclusions/{id}/pin {pinned: bool}`
  - Edit rights for these three actions follow `can_edit_scope`.
  - `POST /api/memory/ask {question, project_key?}` returns `{answer_md, cited: [ConclusionOut]}`.
  - Products: `POST /api/memory/products {name, description, project_ids}`, `PATCH /api/memory/products/{id}`, `DELETE /api/memory/products/{id}`.
  - Admin: `POST /api/admin/memory/dream` returns `MemDreamRun`; `GET /api/admin/memory/dreams` returns the last 20 runs.

- [ ] **Step 1: Write failing tests:**
  - `test_entity_list_counts_only_readable` (a person working in two projects: an outsider sees the count from shared scopes only)
  - `test_entity_detail_hides_unreadable_cards_and_404s_unreadable_project_entity`
  - `test_conclusions_paging_and_status_filter`
  - `test_correct_creates_correction_supersedes_and_suppresses`
  - `test_delete_soft_audited_and_suppressed`
  - `test_permissions_matrix_edit_403_vs_404` (a viewer gets 403 on a readable conclusion; an outsider gets 404; a member gets 403 on an org-scope conclusion and 200 on its own project)
  - `test_reasoning_chain_depth_and_derived`
  - `test_ask_endpoint_and_limits` (an empty question or one over 1,000 chars gives 422)
  - `test_dream_endpoints_admin_only`
  - `test_products_crud`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement. Run `npm run gen:api` in `frontend/` and check that no OpenAPI schema name collides (no `app__…` names; prefix with `Mem` where needed).
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(memory): browse, correct, delete, pin, ask and products api`.

### Task 9: Memory MCP tools and prompt context

**Files:**
- Create:
  - `backend/app/mcp_server/memory_tools.py`, `backend/app/memory/context.py`
  - `backend/tests/memory/test_context.py`, `backend/tests/mcp/test_memory_tools.py`
- Modify:
  - `backend/app/mcp_server/server.py`, `backend/app/main.py` (register the provider)
  - `backend/tests/mcp/test_mcp.py` (tool list)
  - methodology defaults `brainstorm.md`, `plan.md`, `build_implement.md` (one line naming `ask_memory` and `search_memory`)

**Interfaces:**
- Produces:
  - MCP tools, allowed for every run role and for personal tokens, using the token owner's access:

    | Tool | Returns |
    |---|---|
    | `search_memory(query, project_key?)` | up to 10 `{id, entity, text, kind, confidence, source_label}` |
    | `ask_memory(question, project_key?)` | `{answer_md, cited: [{id, text}]}` |

    Errors are tool errors with the REST codes. An unknown project, or one the owner cannot access, gives `project_not_found`.
  - `async memory_context(db, task, role) -> str | None` follows the MEM-6 rules in Global Constraints. It is registered once in `create_app`, after the KB provider. It returns None when there is nothing to add.

- [ ] **Step 1: Write failing tests:**
  - `test_memory_tools_respect_owner_access`
  - `test_ask_memory_tool_not_configured_error` (real mode, no answering model → tool error `memory_answering_not_configured`)
  - `test_tool_list_includes_memory_tools`
  - `test_context_cards_then_conclusions_within_6000_wrapped`
  - `test_context_respects_owner_access`
  - `test_context_none_without_memory_and_for_finish`
  - `test_context_title_with_untrusted_tag_escaped`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(memory): mcp tools and prompt context`.

### Task 10: Frontend — Memory area

**Files:**
- Create:
  - `frontend/src/lib/memory.ts`
  - `frontend/src/app/(app)/memory/page.tsx`, `frontend/src/app/(app)/memory/entity/[id]/page.tsx`
  - `frontend/src/components/memory/{AskMemory,EntityList,ConclusionList,ConclusionItem,ReasoningChain,ProductEditor}.tsx` plus tests
- Modify:
  - `frontend/src/components/shell/Sidebar.tsx` ("Memory", Lucide `Brain`)
  - `frontend/src/lib/errors.ts` (`memory_answering_not_configured`, `memory_unavailable`, `dream_running`)

**Interfaces:**
- Produces:
  - `memKeys` (all start with `"mem"`), `useMemEntities(kind, q)`, `useMemEntity(id)`, `useMemConclusions(entityId, status)` (infinite query on the cursor), `useMemConclusion(id)`.
  - `/memory`:
    - `AskMemory`: a question box (≤ 1,000), an optional project select, the answer rendered with `Markdown` in `.kb-prose`, and the cited conclusions as numbered links to their entity pages. Errors use `errorMessage`.
    - `EntityList`: grouped by kind (Organization, Teams, Projects, Products, People, Agents) with conclusion counts and a filter box.
    - `ProductEditor`: shown to admins and managers.
  - `/memory/entity/[id]`:
    - cards (one per readable scope, labelled with the scope name and "updated <date>")
    - `ConclusionList` with a status filter (Active, Superseded, Deleted) and "Load more"
  - `ConclusionItem`:
    - the text, a kind badge (`observed`, `deduced`, `induced` with its confidence as a percentage, `correction`), a pinned marker, the scope chip, and the source link (`source.link`; "(source deleted)" when null)
    - actions, only when `can_edit`: Correct (inline editor, ≤ 500), Delete (asks first, then explains it will not be re-learned from that source), Pin/Unpin
    - "Why?" expands `ReasoningChain`
  - `ReasoningChain` is a nested list of premises with their kinds. Every level is a link to its conclusion's entity.

- [ ] **Step 1: Write failing tests:**
  - `AskMemory shows answer with numbered citations and errors`
  - `AskMemory sends project_key when chosen`
  - `ConclusionItem hides actions without can_edit`
  - `ConclusionItem correct sends text and delete asks first`
  - `ConclusionItem renders induced confidence and source link or deleted note`
  - `ReasoningChain renders nested premises`
  - `EntityList groups by kind and filters`
  - `conclusion text renders as markdown without raw html` (`<img src=x onerror=…>` is not an element)
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm test`, `npx tsc --noEmit` and `npm run lint`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(frontend): memory area`.

### Task 11: Frontend — AI jobs and dreaming admin

**Files:**
- Create: `frontend/src/components/memory/DreamPanel.tsx` plus a test
- Modify: `frontend/src/components/ai/JobModels.tsx` (`JOB_TEXT` for extraction, dreaming, answering), `frontend/src/app/(app)/admin/ai/page.tsx` (adds `DreamPanel`)

**Interfaces:**
- Produces:
  - `JOB_TEXT` help text:

    | Job | Help |
    |---|---|
    | extraction | "Reads new comments, run summaries, reviews and documents and records short conclusions." |
    | dreaming | "Nightly consolidation: replaces outdated conclusions, deduces and induces new ones, refreshes summary cards." |
    | answering | "Answers questions asked of the memory." |

  - `DreamPanel` shows the last 20 dream runs (trigger, status, started and finished times, stats as "N cards, N replaced, N deduced, N induced") and a "Dream now" button. A 409 shows "A dream run is already in progress."

- [ ] **Step 1: Write failing tests:**
  - `JobModels lists all four jobs with help`
  - `DreamPanel shows runs and dream now`
  - `DreamPanel shows already running`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm test`, `npx tsc --noEmit` and `npm run lint`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(frontend): memory jobs and dreaming admin`.

### Task 12: End-to-end — the memory through the stack

**Files:**
- Create: `frontend/e2e/memory.spec.ts`
- Modify: `README.md` (Memory end-to-end test, and memory overview in the features list)

**Interfaces:**
- Consumes: the full stack with fake AI (`AI_FAKE=true`) and the worker.

- [ ] **Step 1: Write the e2e** `memory.spec.ts` on a fresh stack. Project key `MEM`; teams "Memory Team" and "Memory Outsiders".
  1. An admin configures one provider, then sets the extraction, dreaming, answering and embeddings jobs to it. The Test button works for each.
  2. Create the project MEM with a task, and comment "The billing service retries webhooks three times with HMAC signatures." Wait (poll the API) until the MEM project entity has that conclusion, with the source linking to MEM-1.
  3. On the entity page, delete it (it asks first). Edit the comment to "the billing service retries webhooks three times with HMAC signatures!" and wait for the extraction job to finish (poll `/api/admin/jobs`). The deleted conclusion does not come back, and its source is still shown under the Deleted filter.
  4. Add a KB document in the org space with two sentences sharing the word "billing". Click Dream now and wait for the run to be `done`. The org entity shows a card, and the induced conclusion shows its confidence and a Why? chain with two premises.
  5. Ask "How are webhooks signed?" with the project MEM. The answer cites a conclusion.
  6. An outsider (another team) sees the org card, but none of MEM's conclusions or its card, and asking gives no citation from MEM.
  7. Through MCP with a personal token, `search_memory` and `ask_memory` return the same scoped results.
- [ ] **Step 2:** Run it on the stack. Expected: FAIL until everything is wired.
- [ ] **Step 3:** Fix what it exposes, each test-first in the owning module, as separate `fix(...)` commits.
- [ ] **Step 4:** Run `npx playwright test` (all specs) twice on fresh stacks, plus `uv run pytest -q`, `npm test` and `go test ./...`. Expected: PASS. Tear the stack down with `down -v` and touch only `megoo-e2e`.
- [ ] **Step 5:** Commit: `test(e2e): memory end to end`.

---

## Spec coverage (Plan 5)

| BRD item | Task |
|---|---|
| MEM-1 entities: people, agents, teams, projects, products, organization | 2, 8, 10 |
| MEM-2 inputs: task threads, run metadata, review findings, KB documents (A2A in Plan 6) | 3 |
| MEM-3 continuous learning, conclusions linked to sources | 4 |
| MEM-4 dreaming: replace, deduce, induce (≥ 2 premises, confidence), reasoning chain, summary cards; nightly and on demand | 7, 8, 11 |
| MEM-5 ask the memory, UI and MCP, with citations | 6, 8, 9, 10 |
| MEM-6 context injection | 9 |
| MEM-7 access control | 2, 5, 6, 7, 8, 9 |
| MEM-8 browse, sources, reasoning chain, correct, delete, pin; no re-derivation | 4, 7, 8, 10 |
| MEM-9 hybrid retrieval | 5 |
| MEM-10 per-job models and cost visibility | 1, 11 |
| AGT-31 ask/search memory | 9 |
| ADM-2 memory deletions audited | 8 |
| §5 permissions: correct/delete memory conclusions | 2, 8 |
| R4 memory quality mitigations | 4, 7, 8, 10 |
