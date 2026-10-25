# MegooColab Plan 4 — Knowledge Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** People and agents share a versioned Markdown Knowledge Base. It is organised into organisation, team and project spaces, each with folders. Every revision records its author. Revisions can be compared as a diff. Documents link to tasks and to each other. Search combines full-text and semantic (pgvector) results. Approved designs and plans are filed automatically. Agents read and write the Knowledge Base through MCP, and relevant entries are added to their stage prompts.

**Architecture:**
- **Backend:**
  - A new `kb` module holds spaces, folders, documents, revisions, links and chunks, with access rules that follow space membership.
  - A new `ai` module is the single gateway to LiteLLM. It holds admin-configured providers and per-job models, records usage and cost, and has a deterministic fake mode for tests.
  - A new PostgreSQL-backed job queue (`jobs`) and a worker process (`python -m app.worker`) run background work. The first job embeds document chunks. Plan 5's memory jobs will reuse the queue.
  - Search is hybrid: PostgreSQL full-text search and pgvector cosine similarity, fused by reciprocal rank.
- **Frontend:** a Knowledge Base area with spaces, folder tree, document view and editor, revision history with diffs, backlinks and search. There is also an admin AI settings page.
- **Runner:** unchanged.

**Tech Stack:**
- Added: `litellm` (Python; pin the exact version after checking the current docs with Context7) and the `pgvector` Python package, used for SQLAlchemy's `Vector` type.
- The PostgreSQL image is already `pgvector/pgvector:pg17`.
- Diffs are computed on the server with Python `difflib`. No new frontend dependency is added.
- Everything else is the Plan 1–3 stack.

**Spec:** [docs/brd.md](../../brd.md). This plan covers:
- §6.7 KB-1 to KB-6, with KB-4 limited to approved designs and plans plus final-review summaries (agent-to-agent Q&A filing comes in Plan 6)
- WF-9's "filed in the project's Knowledge Base"
- AGT-31's KB tools
- WF-4's KB context
- ADM-1 AI providers and models
- MEM-10 and NFR-9 per-job model selection, and usage and cost visibility; the embeddings job only, since Plan 5 adds the memory jobs
- the background worker and job queue (§8, §15)
- NFR-1: provider keys are encrypted at rest
- NFR-3: Knowledge Base content is untrusted

**Builds on:** Plans 1–3 on `main`. Reuse:
- `DbSession`, `AuthedUser`, `AdminUser`
- `get_project_for`, `accessible_project_ids`, `can_manage_project`, `user_team_ids`, `project_team_ids`
- `publish`/`Event`, `audit.record`
- `app/core/crypto.encrypt/decrypt`, `NoNulStr` (`app/core/text.py`)
- the Plan 3 `context_providers` hook (`app/workflow/context.py`)
- the MCP `tool_session`, `current_run`, `require_run_task`, `TOOL_ROLES` (`app/mcp_server/`)
- the shared frontend `Markdown` component, which renders images as links
- `api()`, `qk`, `useRealtime` and `errorMessage`

**Staffing assumption:** one implementer per task, executed sequentially. Tasks 1–2 (infrastructure) and Task 3 (data model) are independent of each other.

## Global Constraints

**Spaces and access (KB-1, KB-5)**
- There are three space kinds: `org` (exactly one), `team` (one per team) and `project` (one per project).
- Spaces are created automatically: in a migration backfill for existing teams and projects, and from then on whenever a team or project is created. A team's or project's space is deleted with it.
- Read access:

  | Space | Who can read |
  |---|---|
  | `org` | every active signed-in user |
  | `team` | members of that team, and admins |
  | `project` | users with project access (`accessible_project_ids`), and admins |

- Write access (create, edit, move, delete documents and folders): anyone who can read the space and whose role is not `viewer`. Deleting a document is limited to its creator, a manager of the space (a team manager, or `can_manage_project`), or an admin.
- A user with no read access to a space gets 404, never 403. This also applies to search, backlinks, MCP and prompt context, which never reveal documents in spaces the caller cannot read.
- Agents act with their owner's access (AGT-2).

**Documents and revisions (KB-2)**

| Field | Limit |
|---|---|
| Title | `NoNulStr`, 1–200 chars, unique within its folder |
| Body | Markdown, `NoNulStr`, ≤ 500,000 chars |
| Folder name | 1–100 chars matching `[^/\\]+`, unique among siblings |

- Every save creates a new revision. A revision records `revision` (1, 2, …), `title`, `body_md`, `author_user_id` (the human, or the agent's owner), `author_agent_id|None`, `summary` (≤ 200, optional) and `created_at`.
- Updates must carry `base_revision`. If it is not the latest, the update gets 409 `kb_conflict` and nothing is saved.
- Diff: `GET …/revisions/{a}/diff/{b}` returns `difflib` line operations `[{op: "equal"|"insert"|"delete"|"replace", a_lines, b_lines}]`. Runs of equal lines longer than 6 are collapsed to 3 lines of context on each side.

**Links (KB-6)**
- Wiki-link syntax in the body:
  - `[[PAY-12]]` links to a task.
  - `[[doc:<uuid>]]` or `[[doc:<uuid>|Label]]` links to a document.
- On save, links are extracted into `kb_links(document_id, target_task_id|null, target_document_id|null)`.
- Backlinks show only sources the viewer can read.
- Rendering:
  - A task link becomes a link to the task.
  - A document link becomes a link to the document, with the label or the target's title. A target the viewer cannot read renders as "(restricted document)".
  - Anything else stays plain text.

**Search (KB-3)**
- Full-text: a generated `tsvector` column on the latest revision, built from the title (weight A) and the body (weight B) with the `simple` config.
- Chunks: each latest body is split into chunks of about 3,000 chars with 300-char overlap, cut on paragraph boundaries where possible, and at most 2,000 chunks per document. Each chunk stores `embedding vector` (no fixed dimension) and `embedding_model`.
- Semantic search compares only chunks whose `embedding_model` is the currently configured embeddings model, using cosine distance (pgvector `<=>`, exact scan with no ANN index at this scale).
- Hybrid ranking is reciprocal rank fusion: `score = Σ 1/(60 + rank)` over the full-text list and the semantic list, each limited to the top 50.
- A result is `{document_id, space, title, path, snippet ≤ 300, score}`.
- When no embeddings model is configured, search is full-text only, and the response says `semantic: false`.

**AI gateway (ADM-1, MEM-10, NFR-9)**
- Every LLM or embedding call goes through `app/ai/client.py`. No other module imports `litellm`.
- Providers: `{name, kind (LiteLLM provider prefix, e.g. "openai", "azure", "ollama"), api_key_enc, api_base|None}`. Keys are encrypted with `app/core/crypto` and never returned by the API; the API returns `has_key: bool` instead.
- Job models: `{job: "embeddings", provider_id, model}`. Plan 5 adds `extraction`, `dreaming` and `answering` rows without a schema change.
- Every call records `ai_usage{job, model, input_tokens, output_tokens, cost_usd (litellm cost, or null), ok: bool, error_code|None, created_at}`.
- Fake mode: when `settings.ai_fake` is true (tests and e2e), `embed` returns deterministic 64-dimension unit vectors derived from SHA-256 of the text, with no network call. Its model name is `fake/embed-64`.

**Job queue and worker (§8, NFR-5)**
- Table `jobs`:

  | Column | Notes |
  |---|---|
  | `id` | |
  | `kind` | |
  | `payload` | JSONB |
  | `dedupe_key` | unique while queued or running |
  | `status` | `queued`, `running`, `done` or `failed` |
  | `attempts` | |
  | `max_attempts` | default 5 |
  | `run_after` | |
  | `locked_until` | |
  | `last_error` | ≤ 500 |
  | `created_at`, `finished_at` | |

- The worker claims jobs with `SELECT … FOR UPDATE SKIP LOCKED` and a 5-minute lease.
- Retry backoff is `min(2^attempts × 10 s, 1 h)`.
- The worker wakes on `NOTIFY megoo_jobs` and also polls every 10 s.
- Job handlers are idempotent.
- The worker runs as a separate Compose service, `worker`, from the same backend image.

**Untrusted content (NFR-3)**
- Knowledge Base bodies render with the shared `Markdown` component: no raw HTML, images become links, and `javascript:` URLs are stripped.
- In prompts, every Knowledge Base excerpt is wrapped `<untrusted source="kb">`.

**Prompt context (WF-4)**
- The KB context provider adds up to 5 excerpts (≤ 8,000 chars in total) under `## Knowledge Base`. They come from a hybrid search over the task title and description, restricted to spaces the agent's owner can read. Each excerpt shows the document path and the revision number.

## Review Focus

1. **Access leaks.** A user or agent loses team membership, or searches across spaces. Search hits, snippets, backlinks, wiki-link labels, MCP results and prompt context must never include anything from a space the caller cannot read now. Tested in Tasks 3, 4, 5, 7 and 8.
2. **Concurrent edits.** Two people, or a person and an agent, save the same document from the same base. Exactly one save wins, the other gets 409 `kb_conflict`, and no revision is lost. Tested in Tasks 4 and 7.
3. **The embeddings provider is missing, failing or changed.** The Knowledge Base still works with full-text search. Embedding jobs retry with backoff and then fail visibly. After the model changes, vectors from different models are never mixed, and documents are re-embedded. Tested in Tasks 1, 2 and 5.
4. **Hostile or odd content.** Examples: huge bodies, NUL characters, `[[doc:…]]` pointing to a restricted or missing document, `<untrusted>` tags or `javascript:` links in a body, moving a document to a space where it is no longer visible, deleting a folder that has documents, or deleting a task that documents reference. Each gives a defined, safe result. Tested in Tasks 3, 4, 5, 8 and 11.
5. **Automatic filing runs twice.** A design is approved twice in a race, a plan is re-approved after a rejection, or a task is renamed. This gives one Knowledge Base document per task and kind, with one revision per approved version and no duplicates. Tested in Task 6.

---

## File Structure

```
backend/app/
  jobs/{models,queue,worker}.py     jobs table, enqueue/claim/finish, worker loop (python -m app.worker)
  worker.py                         entry point: python -m app.worker
  ai/{models,client,router,schemas}.py   providers, job models, usage, embed(), admin API
  kb/models.py                      KbSpace, KbFolder, KbDocument, KbRevision, KbLink, KbChunk
  kb/access.py                      readable_space_ids(user), can_read/can_write/can_delete
  kb/service.py                     create/update/move/delete, revisions, links, diff
  kb/search.py                      chunking, embed job handler, fts + semantic + RRF
  kb/filing.py                      auto-filing of approved designs/plans and final reviews
  kb/router.py                      REST
  kb/context.py                     prompt context provider
  mcp_server/kb_tools.py            kb_search, kb_read, kb_list, kb_write
backend/tests/{jobs,ai,kb}/...
deploy/docker-compose.yml           + worker service

frontend/src/
  lib/kb.ts                         hooks, wiki-link helpers
  app/(app)/kb/page.tsx             spaces overview + search box
  app/(app)/kb/[spaceId]/page.tsx   space: folder tree + documents
  app/(app)/kb/doc/[docId]/page.tsx document view / edit / history
  app/(app)/kb/search/page.tsx
  app/(app)/admin/ai/page.tsx
  components/kb/{FolderTree,DocList,DocView,DocEditor,RevisionHistory,DiffView,Backlinks,SearchResults}.tsx
  e2e/kb.spec.ts
```

---

### Task 1: Job queue and worker process

**Files:**
- Create:
  - `backend/app/jobs/{__init__,models,queue,worker}.py` and `backend/app/worker.py`
  - `backend/tests/jobs/test_queue.py`
  - a migration
- Modify:
  - `backend/app/models.py`
  - `deploy/docker-compose.yml` (a `worker` service: same image, command `python -m app.worker`, same env, depends on db healthy)
  - `deploy/docker-compose.dev.yml`, only if the dev stack runs the backend in Docker; otherwise update the README dev instructions
  - `README.md`

**Interfaces:**
- Produces:
  - `Job` model (columns as in Global Constraints). Partial unique index on `dedupe_key` where `status in ('queued','running')`.
  - `async enqueue(db, kind: str, payload: dict, *, dedupe_key: str|None = None, run_after: datetime|None = None) -> Job|None`
    - Returns `None` when a queued or running job with the same dedupe key exists, using `ON CONFLICT DO NOTHING`.
    - Publishes `NOTIFY megoo_jobs` on commit.
  - `async claim(db, kinds: set[str]) -> Job|None` uses `FOR UPDATE SKIP LOCKED`, takes the oldest job with `run_after <= now`, sets `running`, increments `attempts`, and sets `locked_until = now + 5 min`. A `running` job whose lease has expired is claimable again.
  - `async complete(db, job)`
  - `async fail(db, job, error: str)` re-queues with backoff while `attempts < max_attempts`, and otherwise sets `failed`. `last_error` is cut to 500 chars.
  - `HANDLERS: dict[str, Callable[[AsyncSession, dict], Awaitable[None]]]` and `register(kind)`, a decorator.
  - `async run_worker(stop: asyncio.Event)` loops: claim, run the handler in its own transaction, then complete or fail. It sleeps on LISTEN `megoo_jobs` with a 10 s timeout.
  - The `python -m app.worker` entry point handles SIGTERM gracefully.
  - Admin endpoint `GET /api/admin/jobs?status=` lists the latest 100 jobs `{id, kind, status, attempts, last_error, created_at, finished_at}`.

- [ ] **Step 1: Write failing tests:**
  - `test_enqueue_dedupes_while_queued`
  - `test_claim_skips_locked_rows_two_workers` (two sessions, two jobs; each gets one, never the same)
  - `test_failed_job_backs_off_then_fails_after_max_attempts`
  - `test_expired_lease_is_reclaimed`
  - `test_worker_runs_registered_handler_and_completes` (an in-process `run_worker` with a stop event)
  - `test_handler_exception_records_last_error`
  - `test_admin_jobs_list_admin_only`
- [ ] **Step 2:** Run `uv run pytest tests/jobs -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. Generate the migration against the scratch DB, with named constraints.
- [ ] **Step 4:** Run `uv run pytest -q` (single process). Expected: PASS. Run `docker compose -f deploy/docker-compose.yml config` and check that the worker service is valid.
- [ ] **Step 5:** Commit: `feat(jobs): postgres job queue and worker`.

### Task 2: AI gateway — providers, job models, embeddings, usage

**Files:**
- Create:
  - `backend/app/ai/{__init__,models,schemas,client,router}.py`
  - `backend/tests/ai/test_ai.py`
  - a migration
- Modify:
  - `backend/pyproject.toml` (add `litellm`, pinned after checking Context7)
  - `backend/app/core/config.py` (add `ai_fake: bool = False`)
  - `backend/tests/conftest.py` (sets `AI_FAKE=true`)
  - `backend/app/main.py`, `backend/app/models.py`

**Interfaces:**
- Produces:
  - Models:
    - `AiProvider{id, name (unique, ≤ 100), kind (≤ 50), api_key_enc|None, api_base|None (≤ 500), created_at}`
    - `AiJobModel{job (PK, ≤ 50), provider_id (FK, SET NULL), model (≤ 200), updated_at}`
    - `AiUsage` (as in Global Constraints)
  - `class AiNotConfigured(Exception)`
  - `async embed(db, texts: list[str], *, job: str = "embeddings") -> tuple[str, list[list[float]]]` returns `(model_name, vectors)`.
    - It resolves the job's provider and model. It calls `litellm.aembedding(model=f"{kind}/{model}", input=texts, api_key=…, api_base=…)` in batches of at most 64 inputs. It records `AiUsage` per call, with `ok=False` and the error class name on failure, and re-raises.
    - In fake mode it returns `("fake/embed-64", …)`.
  - `async current_model(db, job) -> str|None` returns the configured `"<kind>/<model>"`, `"fake/embed-64"` in fake mode, or `None`.
  - Admin endpoints (`AdminUser`):
    - `GET/POST/PATCH/DELETE /api/admin/ai/providers`
      - The input carries `api_key` write-only.
      - The output is `{id, name, kind, api_base, has_key}`.
      - Deleting a provider that is in use gets 409 `provider_in_use`.
    - `GET /api/admin/ai/jobs` returns `[{job, provider_id, model}]`, listing known jobs: `["embeddings"]`.
    - `PUT /api/admin/ai/jobs/{job} {provider_id, model}`. Changing the embeddings model publishes the event `ai.embeddings_model_changed`; Task 5 reacts to it.
    - `POST /api/admin/ai/jobs/{job}/test` runs one tiny call (embed `["ping"]`) and returns `{ok, model, error|None}`.
    - `GET /api/admin/ai/usage?days=30` returns per-day, per-job, per-model totals `{day, job, model, calls, failures, input_tokens, output_tokens, cost_usd}`.
  - All changes are audited as `ai.provider.*` and `ai.job.updated`.

- [ ] **Step 1: Write failing tests:**
  - `test_provider_key_encrypted_and_never_returned` (raw DB check that the stored value is not the plaintext; responses carry `has_key` only)
  - `test_embed_fake_is_deterministic_64d_unit` (same text gives the same vector; the norm is about 1)
  - `test_embed_not_configured_raises_when_not_fake` (with fake mode off)
  - `test_embed_records_usage_and_failure` (monkeypatch `litellm.aembedding` to succeed, then to raise; usage rows record `ok` true and false with the error code)
  - `test_embed_batches_64`
  - `test_admin_only` (403 for a member)
  - `test_delete_provider_in_use_409`
  - `test_usage_endpoint_aggregates`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement. Check LiteLLM's current `aembedding` signature, usage fields and cost helper with Context7 before writing `client.py`. If Context7 is unavailable, read the installed package's source (`litellm/main.py`, `cost_calculator.py`) instead, and say which in the report. Generate the migration.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(ai): litellm gateway, providers, job models and usage`.

### Task 3: Knowledge Base data model and access

**Files:**
- Create:
  - `backend/app/kb/{__init__,models,access}.py`
  - `backend/tests/kb/test_access.py`
  - a migration that runs `CREATE EXTENSION IF NOT EXISTS vector` and backfills spaces
- Modify:
  - `backend/app/teams/service.py` and `backend/app/projects/service.py` (create the space on team or project creation)
  - `backend/app/models.py`

**Interfaces:**
- Produces:
  - Models:
    - `KbSpace{id, kind (org|team|project), team_id|None (CASCADE), project_id|None (CASCADE), created_at}`. Unique on kind for `org`, on `team_id` and on `project_id`.
    - `KbFolder{id, space_id (CASCADE), parent_id|None (CASCADE), name, created_by, created_at}`. Unique on (`space_id`, `parent_id`, `name`); handle NULL `parent_id` with a partial unique index for root folders.
    - `KbDocument{id, space_id (CASCADE), folder_id|None (SET NULL makes it root), title, latest_revision: int, created_by, created_at, updated_at, search_tsv (generated tsvector from the latest title and body, stored on the document)}`. Keep a copy of the latest body in `body_md` on the document for the generated column. Unique on (`space_id`, `folder_id`, `title`); handle NULL `folder_id` with a partial unique index.
    - `KbRevision{id, document_id (CASCADE), revision, title, body_md, summary|None, author_user_id|None (SET NULL), author_agent_id|None (SET NULL), created_at}`. Unique on (`document_id`, `revision`).
    - `KbLink{id, document_id (CASCADE), target_task_id|None (CASCADE), target_document_id|None (CASCADE)}`. Check constraint: exactly one target.
    - `KbChunk{id, document_id (CASCADE), revision, ordinal, text, embedding: Vector (no dim)|None, embedding_model|None}`.
    - `KbFiling{task_id (CASCADE), kind (design|plan|review), document_id (CASCADE)}`. Primary key (`task_id`, `kind`). Task 6 uses it.
  - `access.py`:
    - `async readable_space_ids(db, user) -> set[UUID]`
    - `async can_read(db, user, space) -> bool`
    - `async can_write(db, user, space) -> bool`
    - `async can_delete_document(db, user, doc) -> bool`
    - `async get_space_for(db, user, space_id, write=False) -> KbSpace` (404 when unreadable, 403 when readable but not writable)
    - `async get_document_for(db, user, doc_id, write=False) -> tuple[KbDocument, KbSpace]`
    - `async org_space(db) -> KbSpace`
    - `async space_for_project(db, project_id) -> KbSpace`
  - All access rules are exactly as in Global Constraints.

- [ ] **Step 1: Write failing tests:**
  - `test_backfill_creates_org_team_project_spaces` (run the migration-equivalent `ensure_spaces()` on existing rows)
  - `test_new_team_and_project_get_spaces`
  - `test_access_matrix`:
    - org readable by all
    - team space by members only
    - project space by project members
    - admin reads everything
    - a viewer can read but not write
  - `test_losing_team_membership_removes_access` (Review Focus 1)
  - `test_unreadable_space_is_404_not_403`
  - `test_space_deleted_with_project`
  - `test_vector_extension_present`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement. Generate the migration against the scratch DB with named constraints, the generated column, and the backfill in the upgrade. Check downgrade and upgrade on `megoo_migrate`.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(kb): spaces, folders, documents, revisions and access`.

### Task 4: Knowledge Base REST API — documents, folders, revisions, diff, links

**Files:**
- Create: `backend/app/kb/{service,router,schemas}.py`, `backend/tests/kb/test_api.py`
- Modify:
  - `backend/app/main.py`
  - `backend/app/core/events.py` (`Event.team_id: UUID|None = None`, `Event.space_id: UUID|None = None`)
  - `backend/app/realtime/router.py`:
    - team-scoped events go to members of that team, using the team ids cached when the socket connects and refreshed on `membership.changed`
    - project-scoped events behave as before
    - org-scoped KB events have no team or project and go to everyone

**Interfaces:**
- Consumes: `access.*` (Task 3).
- Produces:
  - `parse_links(body: str) -> tuple[set[str], set[UUID]]` returns the task keys from `[[KEY-N]]` and the document ids from `[[doc:<uuid>(|label)?]]`. Invalid forms are ignored.
  - `async create_document(db, user, space, folder_id, title, body, *, agent_id=None, summary=None) -> KbDocument`
  - `async update_document(db, user, doc, *, base_revision: int, title=None, body=None, summary=None, agent_id=None) -> KbDocument` returns 409 `kb_conflict` when `base_revision != latest_revision`. It locks the row FOR UPDATE.
  - Both functions:
    - write a `KbRevision`;
    - refresh `KbLink` rows (only links to tasks and documents that exist, in any space; visibility is applied when reading);
    - enqueue `kb.embed` with dedupe key `kb.embed:<doc_id>` (Task 5 registers the handler; before Task 5 the job stays queued harmlessly);
    - publish `Event(type="kb.updated", space_id, team_id|project_id per space)`.
  - `async move_document(db, user, doc, *, space_id, folder_id) -> KbDocument` needs write access to both spaces.
  - `async delete_document(db, user, doc)`
  - Folders:
    - `async create_folder(db, user, space, parent_id, name)`
    - `async rename_folder(...)`
    - `async delete_folder(db, user, folder, *, recursive: bool)`. Without `recursive`, a folder that is not empty gives 409 `folder_not_empty`. With it, documents move to the parent folder; they are never deleted.
  - `diff(a: str, b: str) -> list[dict]` per Global Constraints.
  - Endpoints, all `AuthedUser`, with access as in Global Constraints:
    - `GET /api/kb/spaces` returns `[{id, kind, name (Organization / team name / project key + name), team_id, project_id, can_write}]` for readable spaces.
    - `GET /api/kb/spaces/{id}/tree` returns `{folders: [{id, parent_id, name}], documents: [{id, folder_id, title, latest_revision, updated_at}]}`.
    - `POST /api/kb/spaces/{id}/folders {parent_id?, name}`, `PATCH /api/kb/folders/{id} {name}`, `DELETE /api/kb/folders/{id}?recursive=`.
    - `POST /api/kb/spaces/{id}/documents {folder_id?, title, body_md, summary?}` returns 201 `DocumentOut`.
    - `GET /api/kb/documents/{id}` returns `DocumentOut{id, space, folder_id, path (folder names joined by "/"), title, body_md, latest_revision, created_by, updated_at, can_write, can_delete}`.
    - `PUT /api/kb/documents/{id} {base_revision, title?, body_md?, summary?}`.
    - `POST /api/kb/documents/{id}/move {space_id, folder_id?}`, `DELETE /api/kb/documents/{id}`.
    - `GET /api/kb/documents/{id}/revisions` returns `[{revision, title, summary, author: {user, agent|null}, created_at}]`.
    - `GET /api/kb/documents/{id}/revisions/{n}`.
    - `GET /api/kb/documents/{id}/revisions/{a}/diff/{b}`.
    - `GET /api/kb/documents/{id}/backlinks` returns readable sources only: `[{id, title, space}]`.
    - `GET /api/tasks/{key}/kb-references` returns the readable documents that link to the task.
    - `POST /api/kb/resolve {doc_ids: [uuid]}` returns `{id: {title, readable: bool}}`, used to render wiki links. An unreadable or missing document returns `readable: false` with no title.
  - Audit actions: `kb.document.deleted`, `kb.document.moved`.

- [ ] **Step 1: Write failing tests:**
  - `test_create_update_creates_revisions_with_author`
  - `test_conflicting_update_409_no_lost_revision` (Review Focus 2; concurrent `asyncio.gather` from the same base gives one 200 and one 409, and the revision count is +1)
  - `test_title_unique_in_folder_409`
  - `test_limits_and_nul` (a body of 500,001 chars gives 422 `too_large`; NUL is stripped)
  - `test_links_parsed_and_backlinks_filtered_by_access` (Review Focus 1)
  - `test_resolve_hides_restricted_titles`
  - `test_move_requires_write_on_both_and_hides_from_old_readers`
  - `test_delete_folder_non_recursive_409_recursive_moves_docs_up`
  - `test_diff_ops_and_context_collapse`
  - `test_delete_task_removes_its_links`
  - `test_kb_events_scoped_to_space_readers` (a team-space event does not reach a non-member's socket)
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(kb): documents, folders, revisions, diff and links API`.

### Task 5: Search — chunking, embeddings job and hybrid ranking

**Files:**
- Create: `backend/app/kb/search.py`, `backend/tests/kb/test_search.py`
- Modify: `backend/app/kb/router.py`, `backend/app/jobs/worker.py` (import the handlers), `backend/app/ai/router.py` (re-embed on a model change)

**Interfaces:**
- Consumes: `jobs.register`, `enqueue`, `ai.embed`, `ai.current_model`, `access.readable_space_ids`.
- Produces:
  - `chunk(body: str, size=3000, overlap=300, limit=2000) -> list[str]` cuts on blank lines when possible, otherwise at the size limit.
  - Job handler `kb.embed(payload: {document_id})`:
    1. Load the latest revision.
    2. If the stored chunks already match that revision and `current_model`, do nothing.
    3. Otherwise delete the old chunks, insert the new ones, and embed them. On `AiNotConfigured`, store the chunks without embeddings and complete. Any other error re-raises, which triggers a retry.
  - When the embeddings model changes, enqueue `kb.reembed_all`. That job enqueues `kb.embed` for every document (deduped) in pages of 500.
  - `async search(db, user, query: str, *, space_ids: set[UUID]|None = None, limit: int = 20) -> {semantic: bool, results: [...]}`:
    - full-text uses `websearch_to_tsquery('simple', q)` ranked by `ts_rank_cd`;
    - semantic embeds the query and orders by `embedding <=> qvec`, restricted to `embedding_model == current_model`;
    - both lists are restricted to `readable_space_ids(user) ∩ space_ids`;
    - results are fused with RRF k=60 and grouped by document, taking the best chunk's snippet.
  - Endpoint: `GET /api/kb/search?q=&space=&limit=` returns `{semantic, results: [{document_id, space: {id, kind, name}, title, path, snippet, score}]}`. `q` must be 1–500 chars, otherwise 422.

- [ ] **Step 1: Write failing tests** (fake AI mode):
  - `test_chunking_boundaries_overlap_limit`
  - `test_embed_job_idempotent_and_reembeds_on_new_revision`
  - `test_not_configured_falls_back_to_fts` (fake mode off and no model: `semantic: false`, full-text results still returned)
  - `test_model_change_never_mixes_vectors` (chunks with an old model are excluded from semantic search until re-embedded; `reembed_all` re-embeds them; Review Focus 3)
  - `test_search_never_returns_unreadable_spaces` (Review Focus 1)
  - `test_hybrid_rrf_orders_exact_title_match_first`
  - `test_embed_failure_retries_then_failed_job_visible`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(kb): hybrid full-text and semantic search`.

### Task 6: Automatic filing — approved designs, plans and final reviews

**Files:**
- Create: `backend/app/kb/filing.py`, `backend/tests/kb/test_filing.py`
- Modify: `backend/app/workflow/documents.py` (call on approval), `backend/app/workflow/finish.py` or `build.py` (call when a final review is approved)

**Interfaces:**
- Consumes: `kb.service.create_document`/`update_document`, `access.space_for_project`, the `KbFiling` model.
- Produces:
  - `async file_document(db, task, kind: "design"|"plan", doc: WorkflowDocument, approver: User) -> KbDocument`:
    - Target: the project space, folder `Designs & Plans` (created if missing) and subfolder `<TASK-KEY>`. The title is `Design` or `Plan`.
    - On the first approval, it creates the KB document. Each later approved version adds a revision. The body is `# <TASK-KEY> — <task title>\n\n<approved body>`.
    - Author: `author_user_id` is the agent's owner and `author_agent_id` is the task's agent. For connect_only workflows it is the human assignee and no agent.
    - The summary is `Approved v<n> by <approver>`.
    - It is idempotent through `KbFiling(task_id, kind)` and a row lock. A repeated or racing approval of the same version adds no revision: compare the body with the latest revision.
  - `async file_final_review(db, task, review: StepReview)`:
    - Title `Final review`, in the same subfolder.
    - The body lists the verdict, the round, and each finding as `- **<severity>** <file>:<line> — <summary>`. Finding text sits inside a fenced block per finding, so it cannot become active Markdown.
    - Called when a final review is approved, or accepted after `final_review_not_clean`.
  - Both are called inside the existing transactions. A filing failure must not roll back the approval: wrap each call in a savepoint, and log and record `kb.filing_failed` on failure.
  - `WorkflowOut` gains `kb_documents: [{kind, document_id}]` so the UI can link to the filed copies.

- [ ] **Step 1: Write failing tests:**
  - `test_design_approval_files_kb_document_with_agent_author`
  - `test_second_approved_version_adds_revision_not_document` (Review Focus 5)
  - `test_racing_double_approval_files_once`
  - `test_connect_only_author_is_assignee`
  - `test_final_review_filed_with_findings_fenced`
  - `test_filing_failure_does_not_block_approval` (monkeypatch to raise; the approval still commits)
  - `test_task_rename_keeps_same_kb_document`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(kb): file approved designs, plans and final reviews`.

### Task 7: Knowledge Base MCP tools

**Files:**
- Create: `backend/app/mcp_server/kb_tools.py`, `backend/tests/mcp/test_kb_tools.py`
- Modify: `backend/app/mcp_server/server.py`, `backend/app/mcp_server/workflow_tools.py` (`TOOL_ROLES` additions)

**Interfaces:**
- Produces these tools. The caller is the token's user; for a run token, that is the agent's owner.

| Tool | Returns | Notes |
|---|---|---|
| `kb_search(query, space_id?)` | `{semantic, results[≤ 10]}` | |
| `kb_list(space_id?, folder_id?)` | the spaces, or a folder's contents | |
| `kb_read(document_id, revision?)` | `{id, title, path, revision, body_md}` | the body is capped at 100,000 chars, with `truncated: bool` |
| `kb_write(space_id?, document_id?, folder_path?, title, body_md, base_revision?, summary?)` | the document | creates a document when `document_id` is absent (creating missing folders on `folder_path` such as `"guides/api"`); otherwise updates it with `base_revision`, so a conflict returns tool error `kb_conflict`; revisions record `author_agent_id` for run tokens |

- Run-token roles:
  - `kb_search`, `kb_list` and `kb_read` are allowed for every role.
  - `kb_write` is allowed only for `implement`, `step_fix`, `final_fix` and `finish`. Read-only roles are refused with `not_allowed_in_role` (WF-5: Brainstorm and the reviewers only read the KB).
  - For run tokens, these tools are not limited to the run's task: the KB is cross-task by nature. Space access still applies.
- Personal tokens can use all four tools.
- Errors use the REST codes. An unreadable space or document gives tool error `not_found`.

- [ ] **Step 1: Write failing tests:**
  - `test_kb_search_and_read_respect_owner_access` (Review Focus 1)
  - `test_kb_write_refused_for_read_only_roles`
  - `test_kb_write_creates_with_folder_path_and_agent_author`
  - `test_kb_write_conflict_tool_error`
  - `test_kb_read_truncates_large_body`
  - `test_run_token_kb_tools_after_run_ended_401`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement. Update the brainstorm, plan and build methodology texts with one line each saying that `kb_search`/`kb_read` are available. Edit the seed defaults in `methodology_texts/`. Seeding only inserts missing keys, so existing installs keep their texts; note that in the report.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(mcp): knowledge base tools`.

### Task 8: Knowledge Base context in stage prompts

**Files:**
- Create: `backend/app/kb/context.py`, `backend/tests/kb/test_context.py`
- Modify: `backend/app/main.py` (register the provider at startup), `backend/app/workflow/context.py` only if the provider signature needs the run's owner

**Interfaces:**
- Consumes: `context_providers` and `ContextProvider = Callable[[AsyncSession, Task, RunRole], Awaitable[str|None]]` (Plan 3), `kb.search.search`.
- Produces `async kb_context(db, task, role) -> str|None`:
  - It resolves the task's agent owner. If there is no agent and the workflow is connect_only, it uses the human assignee.
  - It searches with the query `title + first 1,000 chars of the description` across that user's readable spaces.
  - It takes the top 5 documents, each with its best chunk, and fits them within 8,000 chars in total.
  - Output: `## Knowledge Base` followed by, per document, `### <path>/<title> (rev <n>)` and the excerpt inside `<untrusted source="kb">…</untrusted>`, wrapped with `wrap_untrusted("kb", …)` from `app/workflow/context.py`, which already stops content from closing the wrapper.
  - It returns `None` when there are no results.
  - It skips the `finish` role: finishing needs no KB.

- [ ] **Step 1: Write failing tests:**
  - `test_context_includes_relevant_excerpts_wrapped`
  - `test_context_respects_owner_access` (a document in a team the owner is not in never appears; Review Focus 1)
  - `test_context_budget_8000`
  - `test_untrusted_tag_in_body_escaped` (Review Focus 4)
  - `test_none_when_no_results`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(kb): knowledge base context in stage prompts`.

### Task 9: Frontend — admin AI settings

**Files:**
- Create: `frontend/src/app/(app)/admin/ai/page.tsx`, `frontend/src/components/ai/{ProviderList,JobModels,UsageTable}.tsx` plus tests
- Modify: the admin navigation, `frontend/src/lib/errors.ts`, and the API types (`npm run gen:api`)

**Interfaces:**
- Consumes: Task 2's endpoints.
- Produces:
  - An admin-only page with three sections:
    - **Providers:** a list, with add, edit and delete. The key field is write-only: it shows "Key saved" when `has_key`, and "Replace key" opens an empty field.
    - **Models per job:** the embeddings job has a provider select and a model text field, with a "Test" button that shows ok or the error.
    - **Usage, last 30 days:** a table by day, job and model, with calls, failures, tokens and cost.
  - Help text:
    - "Model names use LiteLLM's format, for example `openai/text-embedding-3-small`."
    - "Changing the embeddings model re-embeds every document in the background."
  - Error text for `provider_in_use`.

- [ ] **Step 1: Write failing tests:**
  - `ProviderList never shows a key and sends api_key only when replaced`
  - `JobModels test button shows result`
  - `UsageTable renders totals`
  - `non-admin sees forbidden card`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm test`, `npx tsc --noEmit` and `npm run lint`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(frontend): admin ai settings`.

### Task 10: Frontend — Knowledge Base navigation, spaces and folders

**Files:**
- Create:
  - `frontend/src/lib/kb.ts`
  - `frontend/src/app/(app)/kb/page.tsx`
  - `frontend/src/app/(app)/kb/[spaceId]/page.tsx`
  - `frontend/src/components/kb/{FolderTree,DocList}.tsx` plus tests
- Modify: `frontend/src/components/shell/Sidebar.tsx` (a "Knowledge Base" link), `frontend/src/lib/realtime.ts` (`kb.updated` invalidates `["kb"]` queries)

**Interfaces:**
- Produces:
  - `useKbSpaces`, `useKbTree(spaceId)`, `useKbDocument(id)`, `useKbRevisions(id)`, `useKbSearch(q, space)`.
  - `kbPath(doc)`.
  - The spaces overview groups spaces as Organization, then Teams, then Projects, with a search box that goes to `/kb/search?q=`.
  - The space page:
    - a folder tree with expand and collapse, and new folder / rename / delete (delete asks before a recursive delete and explains that documents move up);
    - the document list for the selected folder;
    - a "New document" action, offered only when `can_write`.

- [ ] **Step 1: Write failing tests:**
  - `FolderTree renders nesting and selection`
  - `delete non-empty folder asks and sends recursive`
  - `DocList shows updated dates and opens doc`
  - `no write actions without can_write`
  - `realtime kb.updated invalidates kb queries`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm test`, `npx tsc --noEmit` and `npm run lint`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(frontend): knowledge base spaces and folders`.

### Task 11: Frontend — document view, editor, history and diff, links

**Files:**
- Create:
  - `frontend/src/app/(app)/kb/doc/[docId]/page.tsx`
  - `frontend/src/components/kb/{DocView,DocEditor,RevisionHistory,DiffView,Backlinks}.tsx` plus tests
- Modify: `frontend/src/components/ui/Markdown.tsx` (wiki-link rendering)

**Interfaces:**
- Produces:
  - `DocView`:
    - the title, path, "rev n", "updated by <user> (via <agent>)" and the rendered body;
    - backlinks;
    - Edit, Move and Delete actions, each gated on its own flag.
  - `DocEditor`:
    - title and body fields, with a side-by-side Markdown preview (stacked on narrow screens) and an optional "Summary of change" field;
    - saves with `base_revision`. On 409, it shows "Someone saved a newer version" with "Load latest" (which asks before discarding), and the draft is kept;
    - guards against leaving with unsaved text (`beforeunload` plus an in-app link guard, as in Plan 3's methodology editor).
  - `RevisionHistory` is a list of revisions. Picking two shows `DiffView`: line ops with insert, delete and replace styling, shown with text markers (`+`/`−`) and not by colour alone, and collapsed context.
  - Wiki links in `Markdown`:
    - `[[KEY-N]]` renders as a link to the task.
    - `[[doc:<uuid>|label]]` renders as a link to the document. Titles come from `POST /api/kb/resolve`, batched per rendered body. An unreadable target shows "(restricted document)" as plain text.
    - Any other text inside `[[…]]` stays literal text.
  - Long-form readability (brd §9): the KB body uses the readable sans-serif body font, and IDs and code stay monospace.

- [ ] **Step 1: Write failing tests:**
  - `DocEditor conflict keeps draft and Load latest asks`
  - `DocEditor sends base_revision`
  - `DiffView marks insert/delete with text, not colour only`
  - `Markdown renders task and doc wiki links and restricted placeholder`
  - `wiki link cannot produce javascript href` (Review Focus 4)
  - `Backlinks list`
  - `delete asks then navigates to space`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm test`, `npx tsc --noEmit` and `npm run lint`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(frontend): knowledge base documents, editor and history`.

### Task 12: Frontend — search and task integration

**Files:**
- Create: `frontend/src/app/(app)/kb/search/page.tsx`, `frontend/src/components/kb/SearchResults.tsx` plus tests
- Modify: `frontend/src/components/task/TaskView.tsx` (a "Referenced in Knowledge Base" section), `frontend/src/components/workflow/DocumentView.tsx` ("View in Knowledge Base" for filed designs and plans, using `WorkflowOut.kb_documents`)

**Interfaces:**
- Produces:
  - The search page:
    - a query box and a space filter;
    - results with the title, path, space chip, snippet with the matched words highlighted (escaped, never HTML) and the score;
    - a notice "Semantic search is off — an admin can configure an embeddings model" when `semantic: false`.
  - The task view lists `GET /api/tasks/{key}/kb-references`.
  - The workflow document view links to the filed KB copy.

- [ ] **Step 1: Write failing tests:**
  - `SearchResults highlights terms without HTML injection` (Review Focus 4)
  - `semantic-off notice`
  - `task view shows references`
  - `DocumentView shows View in Knowledge Base link when filed`
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm test`, `npx tsc --noEmit` and `npm run lint`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(frontend): knowledge base search and task links`.

### Task 13: End-to-end — the Knowledge Base through the stack

**Files:**
- Create: `frontend/e2e/kb.spec.ts`
- Modify: `deploy/docker-compose.yml` e2e settings (`AI_FAKE=true` for the e2e env file only), `README.md`

**Interfaces:**
- Consumes: the full stack, including the worker service, with fake AI.

- [ ] **Step 1: Write the e2e** `kb.spec.ts` on a fresh stack. The project key is `KBX`, distinct from the other specs.
  1. An admin configures an embeddings provider, which fake mode accepts. The Test button shows ok.
  2. Create a folder and a document in the org space. Edit it twice, the second time from a stale tab, which gives 409 and keeps the draft. Open History and diff revisions 1 and 3.
  3. Create a project-space document with `[[KBX-1]]` and `[[doc:<org doc id>]]`. The task shows "Referenced in Knowledge Base". The org document shows the backlink.
  4. Search finds both documents by full text. A semantic-only query (a synonym the fake vectors match) also returns results once the worker has embedded them. Wait on the API, not a timer.
  5. A member of another team does not see the team-space document in search or backlinks (Review Focus 1).
  6. Through MCP with a personal token: `kb_search`, `kb_read`, then `kb_write`, creating `guides/api/Webhooks`. The document appears live in the UI.
  7. Run the workflow e2e helper's design approval for one task (reuse the Plan 3 helpers or the API): the approved design appears under `Designs & Plans/<KEY>/Design` with the agent as author.
- [ ] **Step 2:** Run it on the stack. Expected: FAIL until everything is wired.
- [ ] **Step 3:** Fix what it exposes, each fix test-first in the module that owns it, as separate `fix(...)` commits.
- [ ] **Step 4:** Run `npx playwright test` (all specs) twice on a fresh stack, plus `uv run pytest -q`, `npm test` and `go test ./...`. Expected: PASS. Tear the stack down with `down -v` and touch only `megoo-e2e`.
- [ ] **Step 5:** Commit: `test(e2e): knowledge base end to end`.

---

## Spec coverage (Plan 4)

| BRD item | Task |
|---|---|
| KB-1 spaces and folders | 3, 4, 10 |
| KB-2 human editing, agent read/write, versioned with author, diff | 4, 7, 11 |
| KB-3 full-text and semantic search | 5, 12 |
| KB-4 automatic contributions: designs, plans, review summaries (agent-to-agent Q&A in Plan 6) | 6 |
| KB-5 permissions follow the space | 3, 4, 5, 7, 8 |
| KB-6 links to tasks and documents | 4, 11, 12 |
| WF-9 filing in the Knowledge Base | 6, 12 |
| WF-4 KB context in prompts | 8 |
| AGT-31 KB tools | 7 |
| ADM-1 AI providers and models | 2, 9 |
| MEM-10 and NFR-9 per-job models and cost visibility (embeddings) | 2, 9 |
| §8 and §15 background worker and job queue | 1 |
| NFR-1 encrypted provider keys | 2 |
| NFR-3 untrusted KB content | 8, 11, 12 |
