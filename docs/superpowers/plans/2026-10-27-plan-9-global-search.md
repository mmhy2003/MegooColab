# MegooColab Plan 9 — Global Search with Meilisearch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One search box (Ctrl+K) and a full results page with filters. Both find tasks, documents, projects, teams,
people, agents and questions as you type, forgive typos, and show each person only what they can open. They run on
a required Meilisearch service.

**Architecture:**
- **Backend:** a new module, `app/search`.
  - **One Meilisearch index.** Each document is `{kind}-{uuid}` and carries a `readers` list of permission tokens
    (`all`, `user:<id>`, `project:<id>`, `space:<id>`).
  - **Staying current.** SQLAlchemy session hooks note every change to an indexed model or its children and queue a
    deduplicated `search.sync` job in the same transaction. The worker then rebuilds that one document from the
    database, or deletes it.
  - **Permissions at search time.** The search service turns the user into reader tokens through the existing
    access helpers on every search, so a permission change needs no reindex.
  - **One way in.** The browser only calls MegooColab's `/api/search/*`. The Meilisearch key never leaves the
    server.
- **Frontend:**
  - a `SearchBox` dialog (Ctrl+K, and a header button);
  - a `/search` page with a filter sidebar, taking the chosen mockup's layout;
  - small cards for people and agents;
  - a Search section in admin settings.
- **Install:** a `meilisearch` service in the production compose, the dev compose and CI.

**Tech Stack:**
- Plans 1–8 stack.
- **New:** the official Python client `meilisearch` (sync, so it is called with `asyncio.to_thread`), and the
  server image `getmeili/meilisearch:v1.55.0`.
- No new frontend dependency.

**Spec:** [docs/superpowers/specs/2026-10-27-global-search-design.md](../specs/2026-10-27-global-search-design.md) (approved). Mockup: [assets/2026-10-27-global-search-mockup.html](../specs/assets/2026-10-27-global-search-mockup.html) (option B).

**Builds on:** Plans 1–8 on `main`. Reuse:
- **Access rules:** `projects.access.accessible_project_ids`, `kb.access.readable_space_ids`,
  `a2a.access.can_read_question` (whose rule the question readers mirror) and `teams` membership.
- **Knowledge Base:** `kb.search.search` (meaning search).
- **AI:** `ai.current_model(db, "embeddings")` (whether an embeddings provider is configured).
- **Jobs:** `jobs.queue` (`register`, `register_periodic`, the job insert with `dedupe_key`, `pg_notify`), and
  `worker.HANDLER_MODULES`.
- **Admin:** `audit.record`, and the admin settings page.

## Global Constraints

**The index**
- One index, named by `settings.meili_index` (default `"megoo"`).
- Document id: `f"{kind}-{uuid}"`.
- Kinds, in display order: `task`, `document`, `project`, `team`, `person`, `agent`, `question`.
- Fields: `id`, `kind`, `key`, `title`, `body`, `comments`, `url`, `readers`, `project_id`, `project_key`,
  `status`, `assignee`, `type`, `labels`, `updated_at` (unix seconds) and `card` (an object, used for people and
  agents).

**Index settings** (applied by `ensure_index`):
- `searchableAttributes`: `["key", "title", "body", "comments"]`.
- `filterableAttributes`: `["kind", "readers", "project_id", "status", "assignee", "type", "labels", "updated_at"]`.
- `sortableAttributes`: `["updated_at"]`.
- `typoTolerance.disableOnAttributes`: `["key"]`. Otherwise the defaults: one typo from 5 letters, two from 9.
- `faceting.maxValuesPerFacet`: `100`.

**Searching**
- Every search uses `matchingStrategy: "all"`.
- Highlights use the private-use characters `` (start) and `` (end). The frontend splits on them and
  renders `<mark>` elements. **Never `dangerouslySetInnerHTML`**: agent- and human-written text reaches the browser
  this way.

**Readers**
- **task:** `["project:<project_id>"]`.
- **document:** `["space:<space_id>"]`.
- **project:** `["project:<id>"]`.
- **team, person (active users only), agent:** `["all"]`.
- **question:** `["project:<target_project_id>", "project:<from task's project_id>" (if any), "user:<asked_by_user_id>" (if any)]`.
- **A user's tokens:**
  - always `all` and `user:<id>`;
  - `project:<p>` for each p in `accessible_project_ids`;
  - `space:<s>` for each s in `readable_space_ids`.
- **Admins** search with no readers filter. This holds because every rule above lets an admin open everything.

**What each kind carries**

| kind | key | title | body | url |
|---|---|---|---|---|
| task | `PAY-42` | title | description (the comments go in `comments`) | `/projects/PAY/board?task=PAY-42` |
| document | — | title | body | `/kb/doc/<id>` |
| project | `PAY` | name | description | `/projects/PAY/board` |
| team | — | name | description | `/teams/<id>` |
| person | — | name | email | none: opens the card |
| agent | — | name | owner's name | none: opens the card |
| question | `PAY-Q7`-style key `<target key>-Q<number>` | title | body, then the answer | `/questions/<id>` |

- **Task extras:**
  - `comments`: the task's newest comments joined, at most 20,000 characters.
  - `status`: the column's category: `before`, `working`, `review` or `done`.
  - `assignee`: `user:<id>` or `agent:<id>`.
  - `type` and `labels`: label names.
- **Document extras:** `project_id` and `project_key`, when the document is in a project space.
- **Cards:**
  - person `card`: `{email, teams: [{id, name}]}`.
  - agent `card`: `{owner_name, projects: [{id, key}]}`. The service drops the projects the viewer cannot read
    before returning it.

**API**
- `GET /api/search/quick?q=`
  - Takes `q`, 1–200 characters.
  - Returns `{groups: [{kind, hits: [Hit]}], total: int}`: at most 5 hits per kind, kinds in display order, empty
    groups left out.
- `GET /api/search`
  - **Query:** `q` (1–200), `kind`, `project`, `status`, `assignee`, `type`, `label` (each repeatable), `updated`
    (`7d`|`30d`|`365d`), `sort` (`relevance`|`newest`), `offset` (≥ 0, step 20) and `meaning` (bool).
  - **Response:** `{hits: [Hit], total, facets: Facets, meaning: [Hit] | null, meaning_available: bool}`.
  - **Page size:** 20.
- **Hit:** `{kind, id, title, key, url, snippet, project_key, status, updated_at, card}`.
- **Facets:** `{kind: {k: n}, project: [{id, key, count}], status: {s: n}, assignee: [{id, name, count}],
  type: {t: n}, label: {l: n}}`. Facets come only from filtered, reader-restricted queries.
- **Validation:** an unknown filter value is 422 `invalid_filter`. UUID filters must parse. Label and type values
  are matched against a whitelist (`TaskType`), or quoted with `"` and `\` escaped.
- **Unavailable:** Meilisearch down or erroring gives 503 `search_unavailable`. Saving anything never depends on
  Meilisearch.
- **Admin:**
  - `GET /api/admin/search` returns `{available, documents, last_rebuild_at}`.
  - `POST /api/admin/search/rebuild` queues `search.rebuild` and is audited as `search.rebuild`.

**Freshness:** a change is indexed within about 2 s (NFR-4). A `search.ensure` periodic job (every 60 s) applies
the settings and queues `search.rebuild` when the index has no documents but the database has any indexed rows.

**Config** (`app/core/config.py`):
- `meili_url: str = "http://localhost:7700"`
- `meili_master_key: str = ""`
- `meili_index: str = "megoo"`

**Copy:**
- Quick box placeholder: "Search tasks, docs, people…".
- The last row: "See all N results".
- Unavailable: "Search is unavailable right now".
- Meaning switch: "Also match by meaning".
- Meaning block heading: "Similar in meaning".

## Review Focus

1. **A private project changes nothing you can see.** It must not change the total, a facet count, a filter value
   or the agent card's project list for someone outside it.
   → Task 4 `test_counts_and_facets_never_include_unreadable_items`.
2. **A removed team member searches again.** The project's tasks and documents disappear at once, with no
   reindex. → Task 4 `test_revoked_membership_takes_effect_on_the_next_search`.
3. **A title like `<img src=x onerror=alert(1)>` or `` text.** It renders as text in the box and on the page,
   and only real highlight markers become `<mark>`.
   → Task 6 `test_snippets_render_text_never_html` and Task 7 `test_results_page_renders_text_never_html`.
4. **A filter value crafted to widen the query.** A label such as `x" OR readers = "all`, a non-UUID project or an
   unknown kind is refused or escaped; it never matches extra items.
   → Task 4 `test_filter_values_cannot_widen_the_query`.
5. **Meilisearch is down.** Creating and editing tasks, comments and documents still succeeds. Search answers 503
   `search_unavailable`, and the queued sync jobs catch up when it returns.
   → Task 3 `test_saves_succeed_and_jobs_catch_up_when_meilisearch_is_down` and Task 4
   `test_search_unavailable_is_503`.

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/search/client.py` | Meilisearch client, `ensure_index`, `SearchUnavailable`, `call()` |
| `backend/app/search/documents.py` | build one index document per kind from the DB; reader tokens |
| `backend/app/search/capture.py` | session hooks that queue `search.sync` for changed items |
| `backend/app/search/jobs.py` | `search.sync`, `search.purge`, `search.rebuild`, periodic `search.ensure` |
| `backend/app/search/service.py` | user tokens, filter building, quick and full search, facets, meaning block |
| `backend/app/search/router.py`, `schemas.py` | `/api/search/*`, `/api/admin/search*` |
| `frontend/src/lib/search.ts` | hooks, `highlight()` splitter, URL ⇄ filters |
| `frontend/src/components/search/{SearchBox,SearchResults,ResultCard,Highlighted}.tsx` | UI |
| `frontend/src/app/(app)/search/page.tsx` | results page |

---

### Task 1: Meilisearch service, client and index settings

**Files:**
- Create: `backend/app/search/{__init__,client}.py`, `backend/tests/search/{__init__,conftest,test_client}.py`
- Modify:
  - `backend/pyproject.toml` (`uv add meilisearch`)
  - `backend/app/core/config.py`
  - `deploy/docker-compose.yml`, `deploy/docker-compose.dev.yml`, `deploy/.env.example`
  - `.github/workflows/ci.yml` (a `meilisearch` service on 7700 with `MEILI_MASTER_KEY`)
  - `docs/install.md` (the service, its key, its volume, and the note that backups don't need it)
  - `README.md` (start the dev Meilisearch alongside the dev DB)

**Interfaces:**
- Produces:
  - `class SearchUnavailable(Exception)`.
  - `def client() -> meilisearch.Client`, built from the settings and cached per URL and key.
  - `async def call(fn: Callable[..., T], *args, **kwargs) -> T`. It runs `fn` in a thread and turns
    `MeilisearchCommunicationError`, `MeilisearchApiError` (except index-not-found where the caller asks) and
    timeouts into `SearchUnavailable`. The timeout is 5 s.
  - `async def ensure_index() -> None`. It creates the index (primary key `id`) if it is missing, applies the
    Global Constraints settings and waits for the settings task.
  - `async def document_count() -> int`.
  - `async def health() -> bool`.
- Tests: the `meili_index` fixture in `tests/search/conftest.py` sets `settings.meili_index` to
  `f"test_{uuid4().hex[:8]}"`, runs `ensure_index`, yields, then deletes the index. Every later task's search tests
  use it.

- [ ] **Step 1: Start the dev Meilisearch.** Add the service to `deploy/docker-compose.dev.yml`:
  - image `getmeili/meilisearch:v1.55.0`;
  - environment `MEILI_MASTER_KEY: megoo-dev-master-key`, `MEILI_NO_ANALYTICS: "true"`;
  - port `7700:7700`, and volume `devmeili:/meili_data`.

  Start it with `docker compose -f deploy/docker-compose.dev.yml up -d meilisearch`. This is the only new
  container. Then set `MEILI_MASTER_KEY=megoo-dev-master-key` in the test environment (conftest default).
- [ ] **Step 2: Write failing tests** in `tests/search/test_client.py`:
  - `test_ensure_index_applies_settings`: after `ensure_index()`, the index's settings equal the Global
    Constraints lists, and `typoTolerance.disableOnAttributes == ["key"]`.
  - `test_ensure_index_is_idempotent`: two calls leave one index with the same settings.
  - `test_unreachable_meilisearch_raises_search_unavailable`: with `settings.meili_url = "http://127.0.0.1:9"`,
    `await call(...)` raises `SearchUnavailable` within the timeout.
  - `test_health_and_document_count`.
- [ ] **Step 3:** Run `uv run pytest tests/search -q`. Expected: FAIL (module missing).
- [ ] **Step 4: Implement.**
  - **Production compose:**
    - a `meilisearch` service: the same image, `MEILI_ENV=production`, `MEILI_MASTER_KEY=${MEILI_MASTER_KEY}`,
      `MEILI_NO_ANALYTICS=true`, a `meilidata:/meili_data` volume, internal network only, and a healthcheck on
      `/health`;
    - `backend` and `worker` get `MEILI_URL=http://meilisearch:7700` and `MEILI_MASTER_KEY`, and depend on its
      health.
  - **`.env.example`:** `MEILI_MASTER_KEY=` with a comment to generate it (`openssl rand -hex 32`, at least 16
    bytes).
  - **Install guide:** a section on the service. It says the index holds no data that can't be rebuilt, so
    backups skip it and a restore rebuilds it.
- [ ] **Step 5:** Run `uv run pytest tests/search -q` and `uvx ruff check app/search tests/search`. Expected: PASS,
  clean.
- [ ] **Step 6:** Commit: `feat(search): Meilisearch service, client and index settings`.

### Task 2: Index documents and reader tokens

**Files:**
- Create: `backend/app/search/documents.py`, `backend/tests/search/test_documents.py`

**Interfaces:**
- Consumes: Task 1 (nothing at runtime; this task is pure DB reads).
- Produces:
  - `KINDS = ("task", "document", "project", "team", "person", "agent", "question")`.
  - `def doc_id(kind: str, id: uuid.UUID) -> str`.
  - `async def build(db, kind: str, id: uuid.UUID) -> dict | None`. It returns the index document per Global
    Constraints, or None when the item no longer exists or must not be indexed (for example a deactivated user).
  - `async def ids_of(db, kind: str) -> AsyncIterator[uuid.UUID]`, every indexable id, for rebuilds.

- [ ] **Step 1: Write failing tests** in `tests/search/test_documents.py`, one per kind:
  - `test_task_document`:
    - Set up project PAY, task 1 with a description, two comments, label `bug`, an assignee and a column of
      category `working`.
    - Check: `build("task", id)` equals the expected dict exactly, with `readers == [f"project:{pid}"]`,
      `key == "PAY-1"`, `comments` containing both comment bodies, `status == "working"`,
      `assignee == f"user:{uid}"`, `labels == ["bug"]` and `url == "/projects/PAY/board?task=PAY-1"`.
  - `test_task_comments_capped_at_20000_characters_newest_first`.
  - `test_document_in_project_space_carries_project`, plus a team-space document with `readers ==
    [f"space:{sid}"]` and `project_id is None`.
  - `test_project_team_person_agent_documents`:
    - People: inactive users give None, and `card.teams` lists the user's teams.
    - Agents: `card.projects` lists the bound projects as `{id, key}`.
    - Readers: `["all"]` for teams, people and agents.
  - `test_question_document_readers`: target project, from-task project and asker give three tokens. Answered
    questions have the answer in `body`, and `key == "QBB-Q1"`.
  - `test_missing_items_build_none`.
- [ ] **Step 2:** Run `uv run pytest tests/search/test_documents.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement `build` with one small builder per kind, each loading only what it needs.
- [ ] **Step 4:** Run the tests and ruff. Expected: PASS, clean.
- [ ] **Step 5:** Commit: `feat(search): index documents and reader tokens`.

### Task 3: Keeping the index current

**Files:**
- Create: `backend/app/search/{capture,jobs}.py`, `backend/tests/search/test_sync.py`
- Modify: `backend/app/worker.py` (`HANDLER_MODULES` adds `app.search.jobs`), `backend/app/main.py` (import
  `app.search.capture` so the hooks are installed)

**Interfaces:**
- Consumes: `documents.build`, `ids_of`, `doc_id`; `client.call`, `ensure_index`, `document_count`.
- Produces:
  - **Capture.** `capture.install()` registers `after_flush` and `before_commit` listeners on
    `sqlalchemy.orm.Session`. `after_flush` maps each new, dirty or deleted instance to `(kind, id)` items in
    `session.info["search_dirty"]`:
    - `Task` → task;
    - `Comment` and `TaskEvent` → their task;
    - `KbDocument` → document;
    - `Project` → project;
    - `Team` and `TeamMember` → the team, and the member as a person;
    - `User` → person;
    - `Agent` and `AgentBinding` → agent;
    - `Question` → question.

    `before_commit` inserts one `search.sync` job per item with `dedupe_key=f"search.sync:{kind}:{id}"` (on
    conflict, do nothing), then `pg_notify`s once. Deleted parents also queue `search.purge`, so items removed by
    `ON DELETE CASCADE` leave the index too:
    - a deleted `Project` purges `{"field": "project_id", "value": "<id>"}`;
    - a deleted `KbSpace` purges `{"field": "readers", "value": "space:<id>"}`.
  - **Jobs:**
    - `search.sync {kind, id}` upserts `build(...)`, or deletes `doc_id` when `build` returns None.
    - `search.purge {field, value}` deletes by filter.
    - `search.rebuild {}` runs `ensure_index`, upserts every kind in batches of 500, deletes documents that are no
      longer in the database, and records `last_rebuild_at` in the org settings.
    - periodic `search.ensure` (60 s) runs `ensure_index`, then queues `search.rebuild` (`dedupe_key="search.rebuild"`)
      when `document_count() == 0` while the DB has tasks, documents, projects or users.
    - On `SearchUnavailable`, each job fails and retries through the queue's backoff.

- [ ] **Step 1: Write failing tests** in `tests/search/test_sync.py`:
  - Setup: use the `meili_index` fixture, and a helper `drain()` that runs every queued `search.*` job inline and
    waits for Meilisearch's tasks.
  - `test_api_changes_reach_the_index`. Through the REST API:
    - create a task;
    - edit its description;
    - comment;
    - move it to a `done` column;
    - add a label;
    - assign it;
    - create a KB document and edit it;
    - create a project;
    - rename a team;
    - invite a user;
    - create an agent;
    - ask a question and answer it.

    After `drain()`, each matching index document shows the change: the comment text, `status == "done"`, the
    label, the new title and so on.
  - `test_deletes_leave_the_index`:
    - Delete a task, a KB document and a deactivated user, then `drain()`; their documents are gone.
    - Delete a project: its tasks and project-space documents are gone through `search.purge`.
  - `test_jobs_are_deduplicated_per_item`: ten edits to one task in one transaction queue one job.
  - `test_saves_succeed_and_jobs_catch_up_when_meilisearch_is_down` (Review Focus 5):
    1. With `settings.meili_url` pointing at a closed port, creating a task through the API returns 201.
    2. The job fails and stays queued for retry.
    3. Restore the URL and `drain()`: the task is indexed.
  - `test_ensure_queues_a_rebuild_when_the_index_is_empty`, and `test_rebuild_restores_and_prunes`: a stray
    document for a deleted task is removed.
- [ ] **Step 2:** Run `uv run pytest tests/search/test_sync.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement.
  - The hooks run inside the async session's greenlet, so `session.execute(...)` is allowed in `before_commit`.
  - Skip the hooks entirely when `session.info.get("search_skip")` (the jobs' own sessions).
- [ ] **Step 4:** Run `uv run pytest tests/search -q`, then the whole backend suite (`uv run pytest -q`), so the
  hooks break nothing elsewhere. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(search): keep the index current through queued sync jobs`.

### Task 4: Search API

**Files:**
- Create: `backend/app/search/{service,router,schemas}.py`, `backend/tests/search/test_api.py`
- Modify: `backend/app/main.py` (routers)

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `async def reader_tokens(db, user) -> list[str] | None` (None for admins).
  - `def build_filter(tokens: list[str] | None, f: Filters) -> list`, a Meilisearch filter array. It escapes `"` and
    `\` in every string and validates UUIDs and enums.
  - `async def quick(db, user, q) -> QuickOut`: one `multi_search` with one query per kind (limit 5) and one with
    limit 0 for the total.
  - `async def full(db, user, q, f: Filters, sort, offset, meaning) -> SearchOut`.
    - Facets come from `facetDistribution` on the same filtered query, with project ids turned into keys and
      assignee tokens into names from the DB.
    - The meaning block applies when `meaning` is set, an embeddings model is configured, and the kind filter is
      empty or includes `document`. It holds `kb.search.search(db, user, q, limit=5)` results whose documents are
      not already among the hits, as document Hits.
  - Agent cards: `card.projects` is filtered to the viewer's readable projects.
  - Endpoints as in Global Constraints. `/api/search*` needs a signed-in user. `/api/admin/search*` is for admins.

- [ ] **Step 1: Write failing tests** in `tests/search/test_api.py`. Use the `meili_index` fixture and `drain()`;
  index via the API.
  - `test_quick_groups_by_kind_with_typos_and_prefix`:
    - "Retry failed card payments" is found by `q=retyr payments` and by `q=paym`.
    - Groups come back in display order, with at most 5 hits each.
    - The highlight markers are `` and ``.
  - `test_keys_match_exactly`: PAY-42 and PAY-24 both exist; `q=PAY-42` returns PAY-42 and not PAY-24.
  - `test_counts_and_facets_never_include_unreadable_items` (Review Focus 1):
    - Project SEC is visible to Ann only. Bob searches a word that occurs in SEC and in his own project.
    - `total`, `facets.kind`, `facets.project`, the assignee facet and the hits all exclude SEC.
    - An agent bound to SEC and PAY shows Bob only `PAY` in `card.projects`.
    - An admin sees both.
  - `test_revoked_membership_takes_effect_on_the_next_search` (Review Focus 2): remove Bob from the team, search
    again with no `drain()`, and SEC's task is gone.
  - `test_questions_follow_their_read_rule`: the asker, a target project member and a from-task project member see
    the question; others don't.
  - `test_filters_sort_and_paging`:
    - `kind=task&status=done&assignee=user:<id>&label=bug&type=bug&updated=7d` narrows correctly.
    - `sort=newest` orders by `updated_at`.
    - `offset=20` returns the second page.
  - `test_filter_values_cannot_widen_the_query` (Review Focus 4):
    - `label=x" OR readers = "all` matches nothing extra.
    - `project=not-a-uuid`, `kind=secret` and `updated=1d` give 422 `invalid_filter`.
    - `q` over 200 characters gives 422.
  - `test_meaning_block`:
    - With `AI_FAKE` embeddings configured, `meaning=true` returns `meaning` hits that aren't already in `hits`,
      and `meaning_available` is true.
    - Without a model, `meaning` is null and `meaning_available` is false.
  - `test_search_unavailable_is_503` (Review Focus 5).
  - `test_admin_search_status_and_rebuild`:
    - Members get 403.
    - Rebuild queues `search.rebuild` and writes the audit entry `search.rebuild`.
    - `GET` reports `available` and `documents`.
- [ ] **Step 2:** Run `uv run pytest tests/search/test_api.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement. Turn `SearchUnavailable` into 503 `search_unavailable` in the router.
- [ ] **Step 4:** Run `uv run pytest tests/search -q` and ruff; then `npm run gen:api` in `frontend/`. Expected:
  PASS.
- [ ] **Step 5:** Commit: `feat(search): quick and full search API with permission filters and facets`.

### Task 5: Frontend data layer

**Files:**
- Create: `frontend/src/lib/search.ts`, `frontend/src/lib/__tests__/search.test.ts`
- Modify: `frontend/src/lib/queries.ts`, `frontend/src/lib/api-types.ts` (generated in Task 4)

**Interfaces:**
- Consumes: the Task 4 endpoints.
- Produces:
  - `qk.searchQuick(q)` and `qk.search(params)`.
  - `useQuickSearch(q: string)`. It is debounced by 120 ms, disabled for an empty `q`, and keeps the previous data
    while typing.
  - `useSearch(params: SearchParams)`.
  - `type Hit`, `type SearchParams`.
  - `paramsFromUrl(sp: URLSearchParams): SearchParams` and `paramsToUrl(p: SearchParams): string`, which
    round-trip.
  - `highlight(text: string): {text: string, mark: boolean}[]`. It splits on ``/``; an unmatched marker
    is dropped, not rendered.
  - `KIND_LABELS`, plain-word labels for the groups: Tasks, Documents, Projects, Teams, People, Agents, Questions.

- [ ] **Step 1: Write failing tests:**
  - `test_highlight_splits_markers_and_ignores_stray_ones`.
  - `test_params_round_trip_through_the_url`: every filter, repeated values, `sort`, `offset` and `meaning`.
- [ ] **Step 2:** Run `npx vitest run src/lib`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npx vitest run src/lib` and `npx tsc --noEmit`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(frontend): search data layer`.

### Task 6: Quick search box

**Files:**
- Create: `frontend/src/components/search/{SearchBox,Highlighted,ResultCard}.tsx`, `frontend/src/components/search/__tests__/SearchBox.test.tsx`
- Modify: `frontend/src/components/shell/Header.tsx` (a search button with the label "Search (Ctrl+K)" and the
  global shortcut)

**Interfaces:**
- Consumes: Task 5.
- Produces:
  - `<SearchBox open onClose />`, a modal dialog.
  - `<Highlighted text />`, which renders `highlight()` output as text and `<mark>` only.
  - `<ResultCard hit />`, the person and agent card.

- [ ] **Step 1: Write failing tests:**
  - `test_ctrl_k_and_cmd_k_open_the_box_and_esc_closes`.
  - `test_results_grouped_in_order_with_see_all`:
    - The group headings come back in display order.
    - The last row reads "See all 37 results" and links to `/search?q=…`.
  - `test_arrow_keys_and_enter_open_the_selected_result`: Enter on a task navigates to its `url`.
  - `test_person_and_agent_open_a_card`: the card shows the email and teams (each linking to `/teams/<id>`), or the
    owner and projects.
  - `test_snippets_render_text_never_html` (Review Focus 3): a title of `<img src=x onerror=alert(1)>` with
    markers renders as text, `document.querySelector("img")` is null, and a `<mark>` holds the matched word.
  - `test_unavailable_message`: a 503 shows "Search is unavailable right now".
  - `test_nothing_shown_before_typing`.
- [ ] **Step 2:** Run `npx vitest run src/components/search`. Expected: FAIL.
- [ ] **Step 3:** Implement. The placeholder is "Search tasks, docs, people…". The box traps focus as `Dialog`
  does.
- [ ] **Step 4:** Run `npx vitest run`, `npx tsc --noEmit` and `npm run lint`. Expected: PASS, clean.
- [ ] **Step 5:** Commit: `feat(frontend): Ctrl+K quick search`.

### Task 7: Results page and admin section

**Files:**
- Create:
  - `frontend/src/app/(app)/search/page.tsx`
  - `frontend/src/components/search/SearchResults.tsx`
  - `frontend/src/components/search/__tests__/SearchResults.test.tsx`
  - `frontend/src/components/admin/SearchAdmin.tsx` (or a section of the existing admin settings page)
- Modify: the admin settings page (a "Search" section)

**Interfaces:**
- Consumes: Tasks 4–6.
- Produces:
  - The `/search` page in the mockup's option B layout: the query box at the top, the filter sidebar on the left,
    and the result list on the right.
  - The admin section shows availability, the document count and the last rebuild, with a "Rebuild index" button
    (with confirmation).

- [ ] **Step 1: Write failing tests:**
  - `test_filters_reflect_facets_and_update_the_url`:
    - The kind checkboxes show their counts.
    - Ticking "Tasks" and status "Done" updates the URL and refetches with `kind=task&status=done`.
  - `test_filters_that_narrow_to_tasks_say_so`: with status chosen, the note "Showing tasks only (status applies to
    tasks)" appears.
  - `test_sort_and_load_more`.
  - `test_meaning_switch_only_when_available`:
    - With `meaning_available: false`, there's no switch.
    - With it true, turning the switch on shows a "Similar in meaning" block.
  - `test_results_page_renders_text_never_html` (Review Focus 3).
  - `test_unavailable_message`.
  - `test_admin_search_section_rebuild`: the button POSTs after confirmation, and members don't see the section.
- [ ] **Step 2:** Run `npx vitest run src/components/search src/components/admin`. Expected: FAIL.
- [ ] **Step 3:** Implement. Status options read "To do / In progress / Review / Done" for `before`, `working`,
  `review` and `done`. Updated options: "Last 7 days / Last 30 days / Last year / Any time".
- [ ] **Step 4:** Run `npx vitest run`, `npx tsc --noEmit` and `npm run lint`. Expected: PASS, clean.
- [ ] **Step 5:** Commit: `feat(frontend): search results page with filters, and admin search status`.

### Task 8: End-to-end

**Files:**
- Create: `frontend/e2e/search.spec.ts`
- Modify: `README.md` (the e2e section lists the spec; the env file needs `MEILI_MASTER_KEY`),
  `.superpowers/e2e.env` (add `MEILI_MASTER_KEY`)

**Interfaces:**
- Consumes: the whole feature on the `megoo-e2e` stack, with project keys `SRA` and `SRB`.

- [ ] **Step 1: Write the spec** `search finds what you may open`:
  1. The admin creates SRA (with Bea) and SRB (admin only). Task SRA-1 is "Retry failed card payments", and task
     SRB-1 is "Retry secret rollout".
  2. As Bea, Ctrl+K and type "retyr": SRA-1 appears within about 2 s of its creation, and SRB-1 never does.
  3. Enter opens SRA-1.
  4. "See all results" opens `/search`, and ticking "Tasks" and "To do" keeps SRA-1.
  5. The admin renames SRA-1, and Bea's search finds the new title.
- [ ] **Step 2:** Run it on a fresh `megoo-e2e` stack (rebuilt, so the compose includes Meilisearch). Then run the
  whole e2e suite. Expected: all pass. Tear the stack down with `down -v`.
- [ ] **Step 3:** Commit: `test(e2e): global search`.

## Spec coverage (Plan 9)

| Spec section | Task |
|---|---|
| §2 Goals: quick box, results page, meaning switch, required service | 6, 7, 4, 1 |
| §2 Non-goals: agents unchanged, KB page unchanged, no fallback | (nothing touches MCP tools or the KB page) |
| §2 Anti-goals: no leak of results, counts, snippets or filter values; revocation; no code; fast; isolated failure | 4 (Review Focus 1, 2, 4), 3 (Review Focus 5), 6 |
| §3 kinds, fields, readers, where results go, cards | 2, 4, 6 |
| §4 quick box behaviour | 6 |
| §4 results page, filters, URL, paging, sort, meaning | 4, 7 |
| §4 when search is down; admin health | 4, 7 |
| §5 freshness, rebuild, permissions at search time, backend-only access | 3, 4 |
| §6 install, client, tests on a real Meilisearch | 1, 8 |
