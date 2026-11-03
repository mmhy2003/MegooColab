# Git Connections and Per-Repository Webhooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adding a git provider asks only what it must. A project's repositories are picked from the provider's own
list. Each repository has its own webhook (address, secret, setup help, one-click setup and status), and the old
shared webhooks keep working.

**Architecture:**
- Backend:
  - The connection's base URL defaults for hosted GitHub and GitLab.
  - New provider-client calls list repositories and manage webhooks for the three kinds.
  - The repository gains webhook fields.
  - A per-repository receiver sits next to the old per-connection one.
  - Project routes serve the picker and the Webhook dialog.
- Frontend: the Admin › Git form is reworked, and Project › Settings › Repositories gains a picker and a Webhook
  dialog.

**Tech Stack:** FastAPI, SQLAlchemy 2 (async), Alembic, httpx (mocked with `httpx.MockTransport` in tests),
Next.js 16 / React 19, TanStack Query, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-03-git-connections-webhooks-design.md` (piece 1 of 4; its "For the later
pieces" section says which events to subscribe to).

## Global Constraints

- **Hosted addresses:** `https://github.com` (API `https://api.github.com`) and `https://gitlab.com`. Gitea/Forgejo
  is always self-hosted and needs an address. Self-hosted GitHub's API is `<address>/api/v3`, as
  `providers.api_base` already computes.
- **Secrets:**
  - 32 random bytes, URL-safe base64 (`secrets.token_urlsafe(32)`), stored with `encrypt` / `decrypt`.
  - Tokens stay write-only.
  - A repository's secret goes only to project managers, through the Webhook dialog's own endpoints, never in a
    repository listing.
- **Verification:** GitHub and Gitea check `X-Hub-Signature-256` (HMAC-SHA256 of the raw body); GitLab checks
  `X-Gitlab-Token`. Keep the 1 MiB body limit and the rate-limit rules: unknown repositories and bad signatures count
  against the sender's address.
- **Webhook address:** `<public_url>/api/git/webhooks/repos/<repo id>`. The old
  `/api/git/webhooks/<connection id>` stays accepted while that connection has a secret.
- **Events subscribed:**
  - GitHub: `pull_request`, `pull_request_review`, `pull_request_review_comment`, `issue_comment`, `push`,
    `check_run`, `check_suite`, `status`.
  - GitLab: push, note (comments), merge request, pipeline.
  - Gitea/Forgejo: push, pull_request, pull request review and comment, issue_comment, status. Confirm the exact
    names against Gitea's API docs (Context7) and record a `Ruling:`.
- **Delivery ids** (deduplication): GitHub `X-GitHub-Delivery`, GitLab `X-Gitlab-Event-UUID`, Gitea
  `X-Gitea-Delivery`. Keep each for 3 days and ignore a repeat with 204.
- **Who can do what:** admins manage connections. Project managers list a connection's repositories, open the Webhook
  dialog, regenerate the secret and use Create it for me.
- **Repository status values:** `not_set_up` (nothing received at its own address), `working` (the last delivery
  verified), `failing` (the last delivery to its own address had a bad signature). Only deliveries to the
  repository's own address count.
- **Migrations:** generate against `megoo_migrate` only (`DATABASE_URL=postgresql+asyncpg://megoo:megoo@localhost:5433/megoo_migrate`,
  plus a throwaway `SECRET_KEY`).
- **Workflow:** no Prettier; match the surrounding comment density and naming. Commits end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Work stays on `feat/git-connections`; no pushing.
- **Docker:** e2e uses only the `megoo-e2e` compose project (stop the dev caddy while it runs). Never touch the
  user's real `megoocolab-*` containers or `cloudflared`. Never run two pytest runs at once.

## Review Focus

1. **A repository moved from one connection to another, or unlinked:** the old host's webhook is removed
   (best-effort), its secret and status are cleared, and a later setup on the new connection starts fresh. Pinned in
   Task 6 by `test_relinking_clears_the_webhook_and_removes_ours`.
2. **Create it for me when the host already has a webhook at this repository's address, and one at the connection's
   old shared address:** the first is updated (no duplicate), the second removed, and webhooks pointing elsewhere are
   untouched. Pinned in Task 5 by `test_install_updates_ours_removes_the_shared_one_and_leaves_others`.
3. **The same delivery sent twice** (the host retries): the second is ignored. Pinned in Task 4 by
   `test_a_repeated_delivery_is_ignored`.
4. **A delivery to a repository whose secret was just regenerated, signed with the old secret:** rejected, and the
   status turns `failing`. Pinned in Task 4 by `test_bad_signature_marks_failing_until_a_good_one`.
5. **GitLab's nested group paths** (`grp/sub/pay`) in the picker and in hook calls: the project id is the URL-encoded
   path. Pinned in Task 2 by `test_gitlab_hooks_use_the_encoded_path`.

---

### Task 1: Data: repository webhook fields, deliveries, hosted defaults

**Files:**
- Modify: `backend/app/projects/models.py` (ProjectRepository), `backend/app/git/models.py`, `backend/app/git/schemas.py`, `backend/app/git/router.py` (`create_connection`, `_out`)
- Create: `backend/migrations/versions/<rev>_repo_webhooks.py` (autogenerated)
- Test: `backend/tests/git/test_connections.py`

**Interfaces:**
- Produces:
  - `ProjectRepository` gains:
    - `webhook_secret_enc: Mapped[str | None] = mapped_column(Text)`
    - `webhook_hook_id: Mapped[str | None] = mapped_column(String(64))`
    - `webhook_last_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))`
    - `webhook_failing: Mapped[bool] = mapped_column(default=False, server_default="false")`
  - `class GitDelivery(Base)` (`__tablename__ = "git_deliveries"`):
    - `delivery_id: Mapped[str] = mapped_column(String(100), primary_key=True)`
    - `received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)`
  - In `app/git/providers.py`:
    - `HOSTED: dict[GitKind, str] = {GitKind.github: "https://github.com", GitKind.gitlab: "https://gitlab.com"}`
    - `def is_hosted(conn: GitConnection) -> bool`
  - Schemas:
    - `GitConnectionIn.base_url: NoNulStr | None = None`: None means the kind's hosted address; for `gitea` it is
      required, else 422 `base_url_required`. `webhook_secret` is removed from `GitConnectionIn`.
    - `GitConnectionOut` gains `hosted: bool` and `waiting_repositories: list[WaitingRepo]`, where
      `class WaitingRepo(BaseModel): project_key: str; name: str`. These are the repositories on the connection with
      `webhook_last_at` null, listed only while `webhook_secret_set`; otherwise `[]`.

- [ ] **Step 1: Write the failing tests** (in `tests/git/test_connections.py`)

```python
async def test_hosted_github_and_gitlab_need_no_address(client, db): ...
    # POST {"name": "GH", "kind": "github", "token": "t"} → 201, base_url "https://github.com", hosted True
    # POST {"name": "GL", "kind": "gitlab", "token": "t"} → base_url "https://gitlab.com", hosted True
    # POST {"name": "Mine", "kind": "gitlab", "base_url": "https://gitlab.acme.io", "token": "t"} → hosted False
async def test_gitea_needs_an_address(client, db): ...
    # POST {"name": "Tea", "kind": "gitea", "token": "t"} → 422, detail contains "base_url_required"
async def test_a_new_provider_has_no_shared_secret(client, db): ...
    # POST with "webhook_secret": "x" → 201, the field is ignored (unknown fields are dropped): webhook_secret_set False
async def test_the_shared_secret_notice_lists_repositories_not_yet_on_their_own(client, db): ...
    # a connection with webhook_secret_enc set, two repositories in project PAY linked to it, one with webhook_last_at
    # set → GET /api/admin/git-connections: waiting_repositories == [{"project_key": "PAY", "name": "<the other>"}]
```

- [ ] **Step 2: Run them and watch them fail.** `cd backend && uv run pytest -q tests/git/test_connections.py`.
  Expected: FAIL.
- [ ] **Step 3: Implement**
  - Add the fields and the model, then generate the migration against `megoo_migrate` (Global Constraints).
  - Apply the schema changes.
  - In `create_connection`, set `base_url = body.base_url or providers.HOSTED[body.kind]` and stop reading
    `webhook_secret`.
  - In `_out`, compute `hosted` and `waiting_repositories`. `list_connections` passes the database to build the
    waiting list.
- [ ] **Step 4: Run `tests/git` and `tests/projects` until they pass.** Then update the existing connection tests
  that post a `webhook_secret` to set it on the model instead (the old shared secret is still supported).
- [ ] **Step 5: Commit** `feat(git): hosted providers need no address; repositories hold their own webhook state`

---

### Task 2: Provider client: list repositories and manage webhooks

**Files:**
- Modify: `backend/app/git/providers.py`
- Test: `backend/tests/git/test_providers.py`

**Interfaces:**
- Consumes: `api_base`, `_headers`, `_client`, `GitProviderError` (existing).
- Produces (all in `providers.py`):
  - `@dataclass(frozen=True) class RepoChoice: path: str; url: str; default_branch: str | None`
  - `async def list_repositories(conn: GitConnection, *, q: str = "", page: int = 1, client: httpx.AsyncClient | None = None) -> tuple[list[RepoChoice], bool]`
    - Returns `(items, more)`, 50 per page, with `url` the https web URL.
    - GitHub: `GET /user/repos?per_page=100&page=N&sort=full_name&affiliation=owner,collaborator,organization_member`,
      filtered by `q` (case-insensitive substring of `full_name`) and fetching up to 3 pages to fill 50.
    - GitLab: `GET /projects?membership=true&simple=true&order_by=path&sort=asc&per_page=50&page=N&search=<q>`.
    - Gitea: `GET /user/repos?limit=50&page=N`, filtered by `q` like GitHub.
  - `HOOK_EVENTS: dict[GitKind, list[str]]`, with the values from Global Constraints.
  - `async def list_hooks(conn, path: str, *, client=None) -> list[tuple[str, str]]`: `(hook id, hook url)` pairs.
  - `async def create_hook(conn, path: str, url: str, secret: str, *, client=None) -> str`: returns the hook id.
  - `async def update_hook(conn, path: str, hook_id: str, url: str, secret: str, *, client=None) -> None`
  - `async def delete_hook(conn, path: str, hook_id: str, *, client=None) -> None`: a 404 counts as done.
  - New error code `forbidden` (HTTP 403 without rate-limit headers), meaning the token may not do this.
  - `def hook_page_url(conn, path: str) -> str`: the host's webhook settings page for the repository:
    - GitHub: `<web>/<path>/settings/hooks`
    - GitLab: `<web>/<path>/-/hooks`
    - Gitea: `<web>/<path>/settings/hooks`
- Request bodies:
  - GitHub: `POST /repos/{path}/hooks` with
    `{"name": "web", "active": true, "events": HOOK_EVENTS[github], "config": {"url", "content_type": "json", "secret", "insecure_ssl": "0"}}`.
    Update with `PATCH /repos/{path}/hooks/{id}`, sending `config` and `events`.
  - GitLab: `POST /projects/{quote(path, safe='')}/hooks` with
    `{"url", "token": secret, "push_events": true, "note_events": true, "merge_requests_events": true, "pipeline_events": true, "enable_ssl_verification": true}`.
    Update with `PUT /projects/{id}/hooks/{hook_id}`.
  - Gitea: `POST /repos/{path}/hooks` with
    `{"type": "gitea", "active": true, "events": HOOK_EVENTS[gitea], "config": {"url", "content_type": "json", "secret"}}`.
    Update with `PATCH`.
  - Add `_send(client, conn, method, path, json=None) -> Any`, sharing `_get`'s error mapping and adding `forbidden`.

- [ ] **Step 1: Write the failing tests** (with the existing `_client(routes, seen)` helper)

```python
async def test_github_lists_repositories_filtered_and_paged(): ...
    # /user/repos page 1 returns acme/pay (default_branch main) and acme/web; q="pay" → [RepoChoice("acme/pay", "https://github.com/acme/pay", "main")], more False
async def test_gitlab_lists_with_server_search(): ...
    # seen request has search=pay&membership=true; item path_with_namespace grp/sub/pay, web_url, default_branch
async def test_gitea_lists_repositories(): ...
async def test_github_hook_create_update_list_delete(): ...
    # create posts config.url/secret/content_type json and HOOK_EVENTS[github]; returns "123"; list → [("123", url)]
async def test_gitlab_hooks_use_the_encoded_path(): ...
    # create for "grp/sub/pay" posts to /api/v4/projects/grp%2Fsub%2Fpay/hooks with token=secret and the four *_events true
async def test_a_403_without_rate_limit_is_forbidden(): ...
async def test_delete_hook_treats_404_as_done(): ...
def test_hook_page_url_per_kind(): ...
```

- [ ] **Step 2: Run them and watch them fail.** `cd backend && uv run pytest -q tests/git/test_providers.py`.
  Expected: FAIL (the names are missing).
- [ ] **Step 3: Implement** as in Interfaces.
- [ ] **Step 4: Run `tests/git` until it passes.**
- [ ] **Step 5: Commit** `feat(git): list a provider's repositories and manage their webhooks`

---

### Task 3: The repository picker endpoint, and the connection on hand-entered repositories

**Files:**
- Modify: `backend/app/projects/router.py`, `backend/app/projects/schemas.py`
- Test: `backend/tests/git/test_repo_picker.py` (create)

**Interfaces:**
- Consumes: `providers.list_repositories`, `RepoChoice` (Task 2).
- Produces:
  - `GET /api/projects/{ref}/repositories/choices?connection_id=<uuid>&q=&page=1`
  - Response: `RepoChoicesOut { items: list[RepoChoiceOut{path, url, default_branch: str | None}], more: bool }`.
  - Managers only (`_managed`). An unknown connection gives 404 `git_connection_not_found`. A provider error gives
    502 with the provider code as its detail (`unauthorized`, `forbidden`, `unreachable`, `rate_limited`,
    `bad_response`).
  - `RepoIn.connection_id` already exists. The plan keeps it, and the UI's "Enter it by hand" sends it.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_manager_lists_a_connections_repositories(client, db, monkeypatch): ...
    # monkeypatch providers._client with a MockTransport answering /user/repos; GET .../choices?connection_id=…&q=pay → 200 items[0].path "acme/pay"
async def test_members_cannot_list_and_the_token_never_leaves(client, db, monkeypatch): ...
    # a member (not manager) → 403; the manager's response JSON contains no "token"
async def test_a_provider_refusal_is_a_502_with_its_code(client, db, monkeypatch): ...
    # host answers 401 → 502 detail "unauthorized"
```

- [ ] **Step 2: Run them and watch them fail.** `cd backend && uv run pytest -q tests/git/test_repo_picker.py`.
  Expected: FAIL (404 route).
- [ ] **Step 3: Implement the route** in `projects/router.py`, declared before `/{ref}/repositories/{repo_id}` routes
  so `choices` isn't read as an id.
- [ ] **Step 4: Run `tests/git` and `tests/projects` until they pass.**
- [ ] **Step 5: Commit** `feat(projects): pick a repository from its provider's list`

---

### Task 4: The per-repository webhook receiver, status and deduplication

**Files:**
- Modify: `backend/app/git/router.py` (the webhook section), `backend/app/projects/schemas.py` (`RepoOut`), `backend/app/projects/router.py` (`_repo_out`)
- Test: `backend/tests/git/test_repo_webhooks.py` (create)

**Interfaces:**
- Consumes: `ProjectRepository.webhook_*`, `GitDelivery` (Task 1); `service.rows_for_delivery`,
  `service.queue_refresh` (existing).
- Produces:
  - `POST /api/git/webhooks/repos/{repo_id}`:
    1. Finds the repository and its connection; with either missing, or no secret, it gives 404 counted against the
       IP.
    2. Verifies with the repository's own secret, using the connection's kind and the existing `_signed` logic, which
       is refactored to `def _verified(kind: GitKind, secret: str, request: Request, body: bytes) -> bool`. A failed
       check sets `webhook_failing = True`, commits, counts against the IP, and gives 401.
    3. On success it sets `webhook_last_at = now` and `webhook_failing = False`, then drops a repeated delivery id
       (204).
    4. It inserts the `GitDelivery` and deletes deliveries older than 3 days.
    5. It queues refreshes exactly as the per-connection endpoint does.
  - The per-connection endpoint also records and deduplicates delivery ids, and never touches repository status.
  - `RepoOut` gains `webhook_status: Literal["not_set_up", "working", "failing"]` and
    `webhook_last_at: datetime | None`. Repositories without a connection report `not_set_up`.
  - `def webhook_url(repo_id: uuid.UUID) -> str` in `app/git/service.py`: `f"{settings.public_url.rstrip('/')}/api/git/webhooks/repos/{repo_id}"`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_signed_delivery_marks_working_and_refreshes(client, db): ...
    # repo linked to a github connection, webhook_secret_enc set; tracked PR row #7 for acme/pay
    # POST pull_request delivery signed with the repo secret → 204; repo webhook_status "working", webhook_last_at set; a refresh job queued
async def test_bad_signature_marks_failing_until_a_good_one(client, db): ...
    # signed with "old" → 401, status "failing"; then a good one → "working"
async def test_gitlab_uses_its_token_header(client, db): ...
async def test_a_repeated_delivery_is_ignored(client, db): ...
    # same X-GitHub-Delivery twice → second 204 queues no second refresh job
async def test_unknown_or_secretless_repository_is_404(client, db): ...
async def test_the_shared_address_still_works_and_counts_for_no_repository(client, db): ...
    # old /api/git/webhooks/<connection id> with the connection secret → 204; repo webhook_status stays "not_set_up"
```

- [ ] **Step 2: Run them and watch them fail.** `cd backend && uv run pytest -q tests/git/test_repo_webhooks.py`.
  Expected: FAIL.
- [ ] **Step 3: Implement** as in Interfaces. The existing `tests/git/test_webhooks.py` must still pass unchanged.
- [ ] **Step 4: Run `tests/git` and `tests/projects` until they pass.**
- [ ] **Step 5: Commit** `feat(git): each repository receives its own webhook, with its status and no repeats`

---

### Task 5: The Webhook dialog's endpoints: address, secret, a new one, and Create it for me

**Files:**
- Modify: `backend/app/git/service.py`, `backend/app/projects/router.py`, `backend/app/projects/schemas.py`
- Test: `backend/tests/git/test_repo_webhook_setup.py` (create)

**Interfaces:**
- Consumes: Task 2's hook calls, Task 4's `webhook_url`, `providers.repo_path`.
- Produces, all managers-only on a repository with a connection (otherwise 422 `repository_not_connected`):
  - `GET /api/projects/{ref}/repositories/{repo_id}/webhook` returns `WebhookOut`:
    - `url: str`, `kind: GitKind`, `hook_page_url: str`
    - `status`, `last_at`
    - `installed: bool` (our hook id is saved)
    - `public_url_is_default: bool` (`public_url` is still `http://localhost:8080`)

    It makes the repository's secret on first use. It never returns the secret.
  - `GET .../webhook/secret` returns `{ "secret": str }`.
  - `POST .../webhook/secret` makes a new one and returns `{ "secret": str, "host_updated": bool | None }`:
    - `None`: no hook id was saved;
    - `True`: `update_hook` succeeded;
    - `False`: it failed, and the error is not raised.
  - `POST .../webhook/install` returns `{ "installed": true }`, or 422 with the provider code (`forbidden`,
    `not_found`, `unreachable`, `unauthorized`).
    - Algorithm (`async def install_hook(db, repo, conn) -> None` in `service.py`):
      1. `list_hooks`.
      2. The hook whose url equals the repository's address is updated with `update_hook` (our secret, events) and its
         id saved.
      3. If there is none, `create_hook` runs and its id is saved.
      4. Every hook whose url equals the connection's old shared address
         (`<public_url>/api/git/webhooks/<connection id>`) is deleted.
      5. Hooks with other urls are never touched.
    - Audit: `git.webhook.installed` and `git.webhook.secret_renewed`, with the repository id and no secret.

- [ ] **Step 1: Write the failing tests**

```python
async def test_the_dialog_gets_address_and_status_but_not_the_secret(client, db): ...
async def test_the_secret_is_shown_on_request_and_renewed(client, db, monkeypatch): ...
    # GET secret → s1; POST secret → s2 != s1, host_updated None (nothing installed)
async def test_install_creates_when_none_exists(client, db, monkeypatch): ...
async def test_install_updates_ours_removes_the_shared_one_and_leaves_others(client, db, monkeypatch): ...
    # host lists hooks at: our repo url (id 1), the old shared url (id 2), https://ci.example/hook (id 3)
    # → PATCH id 1, DELETE id 2, nothing on id 3, no POST; webhook_hook_id "1"
async def test_install_without_permission_says_forbidden(client, db, monkeypatch): ...
    # host 403 → 422 detail "forbidden"; the manual steps still work (GET webhook 200)
async def test_renewing_updates_our_hook_on_the_host(client, db, monkeypatch): ...
    # after install, POST secret → host_updated True and the PATCH carried the new secret
async def test_members_get_403(client, db): ...
```

- [ ] **Step 2: Run them and watch them fail.** `cd backend && uv run pytest -q tests/git/test_repo_webhook_setup.py`.
  Expected: FAIL.
- [ ] **Step 3: Implement** as in Interfaces.
- [ ] **Step 4: Run `tests/git` and `tests/projects` until they pass.**
- [ ] **Step 5: Commit** `feat(git): a repository's webhook address, secret and one-click setup`

---

### Task 6: When a repository changes connection or goes away

**Files:**
- Modify: `backend/app/projects/router.py` (`update_repository`, `delete_repository`), `backend/app/git/service.py`
- Test: `backend/tests/git/test_repo_webhook_setup.py`

**Interfaces:**
- Produces `async def forget_hook(repo: ProjectRepository, conn: GitConnection | None) -> str | None` in `service.py`:
  - when `repo.webhook_hook_id` is set and `conn` is not None, it calls `delete_hook` and returns an error code on
    failure, otherwise None;
  - it always clears `webhook_secret_enc`, `webhook_hook_id`, `webhook_last_at` and `webhook_failing`.
- `update_repository` calls it when `connection_id` changes to another value or to null. `delete_repository` calls
  it before deleting.
- A non-null result is returned as a `warning` field on the PATCH response (`RepoOut.warning: str | None`) and is
  logged for the DELETE. Neither blocks the change.

- [ ] **Step 1: Write the failing tests**

```python
async def test_relinking_clears_the_webhook_and_removes_ours(client, db, monkeypatch): ...
    # installed on connection A (hook id 9); PATCH connection_id → B: DELETE hook 9 on A's host; secret/hook id/status cleared
async def test_unlinking_and_deleting_remove_ours_best_effort(client, db, monkeypatch): ...
    # host answers 500 on DELETE → PATCH still 200 with warning "bad_response"; DELETE repository still 204
```

- [ ] **Step 2: Run them and watch them fail.** **Step 3: Implement.** **Step 4: Run `tests/git` and `tests/projects`
  until they pass.**
- [ ] **Step 5: Commit** `feat(git): moving or removing a repository takes its webhook with it`

---

### Task 7: Admin › Git: the provider form

**Files:**
- Modify: `frontend/src/components/git/GitConnections.tsx`, `frontend/src/lib/git.ts`, `frontend/src/lib/api-types.ts` (`npm run gen:api` with a throwaway `SECRET_KEY`)
- Test: `frontend/src/components/git/__tests__/GitConnections.test.tsx` (extend or create)

**Interfaces:**
- Produces in `lib/git.ts`:
  - `export const HOSTED: Partial<Record<GitKind, { label: string; url: string }>>`:
    `github: { label: "GitHub.com", url: "https://github.com" }`, `gitlab: { label: "GitLab.com", url: "https://gitlab.com" }`.
  - `export const TOKEN_HELP: Record<GitKind, string>`, using the spec's wording:
    - the read access needed;
    - "Optional, for one-click webhook setup:" with the webhook permission;
    - "Optional, for an agent to review and merge: write access to pull requests (merge requests)".
  - `export const TOKEN_DOCS: Record<GitKind, string>`, the links:
    - GitHub: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
    - GitLab: https://docs.gitlab.com/user/profile/personal_access_tokens/
    - Gitea: https://docs.gitea.com/development/api-usage
- The form, in order:
  1. Kind as a segmented choice.
  2. For GitHub and GitLab, a "Where" choice between the hosted label and "Self-hosted".
  3. "Server address", shown only for self-hosted or Gitea.
  4. Name.
  5. Access token, with `TOKEN_HELP[kind]` and a "How to make one" link.

  There is no webhook secret field. A hosted choice sends no `base_url`.
- The connection row:
  - no "Webhook URL" field;
  - when `webhook_secret_set`, the notice (spec copy), the `waiting_repositories` list and a "Remove shared secret"
    button. It confirms first when the list isn't empty, then sends `PATCH {webhook_secret: ""}`.

- [ ] **Step 1: Write the failing tests**

```tsx
it("asks for a server address only when self-hosted, and never for a webhook secret", ...)
  // kind GitHub + Where GitHub.com: no "Server address" field, no "Webhook secret"; choose Self-hosted → "Server address" appears; kind Gitea → address shown, no Where choice
it("a hosted provider sends no address", ...) // POST body has no base_url
it("the token says what access it needs, per kind", ...) // GitLab shows "read_api"
it("a provider with the old shared secret lists the repositories still on it and asks before removing it", ...)
```

- [ ] **Step 2: Run them and watch them fail.** **Step 3: Implement.** **Step 4: Run them until they pass, then
  `npx vitest run && npx tsc --noEmit -p . && npx eslint src`.**
- [ ] **Step 5: Commit** `feat(git): a provider form that asks only what it must`

---

### Task 8: Project › Settings › Repositories: the picker, the status and the Webhook dialog

**Files:**
- Create: `frontend/src/components/project/RepoPicker.tsx`, `frontend/src/components/project/WebhookDialog.tsx`
- Modify: `frontend/src/components/project/RepoEditor.tsx`, `frontend/src/lib/git.ts`
- Test: `frontend/src/components/project/__tests__/RepoPicker.test.tsx`, `WebhookDialog.test.tsx`, `RepoEditor.test.tsx` (extend or create)

**Interfaces:**
- Consumes the endpoints of Tasks 3–6.
- `RepoPicker({ projectKey, onPick }: { projectKey: string; onPick: (r: { connectionId: string; path: string; url: string; defaultBranch: string | null }) => void })`:
  - a Provider select (`useConnectionNames`), then a "Repository" search box;
  - debounce 300 ms; the first page loads without typing; "Load more" while `more`;
  - errors show as `gitTestError(code)`.
- Add repository flow in `RepoEditor`:
  - Picking fills Name (the path), URL, Provider (the connection's kind) and Default branch (editable; `main` when the
    host gives none).
  - "Enter it by hand" opens today's form, plus an optional Connection select.
  - The per-row Connection select stays.
- Each row with a connection shows a status pill:
  - "Webhook not set up" (amber), with a "Set up webhook" button;
  - "Webhook working · last event <relative time>" (green), with a "Webhook" button;
  - "Webhook failing" (pink), with a "Webhook" button.
- `WebhookDialog({ projectKey, repo })`:
  - **Address:** Payload URL with Copy (`CopyField`). When `public_url_is_default`, a warning: "This address is the
    default localhost one, which GitHub and GitLab can't reach. Set PUBLIC_URL to the address people use."
  - **Secret:**
    - hidden until Show, which fetches `GET .../webhook/secret`; then Copy;
    - "Make a new one" confirms first ("The old secret stops working at once."), then shows the outcome:
      `host_updated` True "Updated on <host> too", False "Update it on <host> too, or use Create it for me", None
      nothing.
  - **Steps:** the per-kind steps (`HOOK_STEPS: Record<GitKind, string[]>` in `lib/git.ts`, the spec's words), and an
    "Open <host>'s webhook page ↗" link (`hook_page_url`).
  - **Create it for me:** on success "Created on <host>"; on a 422, the plain message (`forbidden` reads: "This
    token can't manage webhooks. Use the steps above, or give the token webhook permission.").
  - **Status:** the status line refetches every 3 seconds while the dialog is open.

- [ ] **Step 1: Write the failing tests**

```tsx
// RepoPicker.test.tsx
it("lists the provider's repositories, searches as you type, and picking fills the form", ...)
it("shows the provider's refusal in plain words", ...)
// WebhookDialog.test.tsx
it("shows the address, hides the secret until Show, and copies both", ...)
it("makes a new secret only after a confirmation, and says whether the host was updated", ...)
it("shows the steps for the repository's host", ...) // GitLab: "Secret token", "Merge request events"
it("Create it for me says when the token can't", ...) // 422 forbidden → the plain message
it("warns when the public address is the default", ...)
// RepoEditor.test.tsx
it("each connected repository shows its webhook status", ...)
it("enter by hand still takes a connection", ...)
```

- [ ] **Step 2: Run them and watch them fail.** **Step 3: Implement.** **Step 4: Run them until they pass, then the
  web suite, tsc and eslint.**
- [ ] **Step 5: Commit** `feat(projects): pick repositories from the provider and set up each one's webhook`

---

### Task 9: e2e, and the whole suite green

**Files:**
- Modify: `frontend/e2e/git.spec.ts`, `frontend/e2e/helpers/fakeGit.ts`

- [ ] **Step 1: Update the fake host** (`fakeGit.ts`):
  - `GET /api/v3/user/repos` answers `[{ full_name: "o/r", html_url: `${baseUrl}/o/r`, default_branch: "main" }]`.
  - `GET` and `POST /api/v3/repos/o/r/hooks` keep the hooks in memory.
  - `PATCH` and `DELETE /api/v3/repos/o/r/hooks/:id` update and remove them.
  - It exposes `hooks: Map<string, { url: string; secret: string }>`.
- [ ] **Step 2: Update `git.spec.ts` step 1:**
  - Add the provider as kind GitHub, Where Self-hosted, Server address `fake.baseUrl`, Token. There is no webhook
    secret any more.
  - It expects no "Webhook URL" on the connection row.
- [ ] **Step 3: Update step 2:** add repository `o/r` through the picker (Provider "Fake GHE", search "r", pick
  `o/r`) instead of the API and the per-row select.
- [ ] **Step 4: Add the webhook check:**
  1. Open "Set up webhook".
  2. Click "Create it for me", and expect `fake.hooks` to hold one hook whose url ends with
     `/api/git/webhooks/repos/<repo id>`.
  3. Post `pullRequestDelivery` signed with that hook's secret to the repository's address (adapting the helper to
     take a URL and a secret).
  4. Expect the row to read "Webhook working".

  Later deliveries in the spec use the repository's address too.
- [ ] **Step 5: Run the backend suite** (`uv run --with pytest-timeout pytest -q --timeout 180`, one run at a time),
  **the web suite, tsc, eslint, and the whole e2e suite on a fresh `megoo-e2e` stack.** Expected: all green.
- [ ] **Step 6: Commit** `test(e2e): providers, the repository picker and per-repository webhooks`
