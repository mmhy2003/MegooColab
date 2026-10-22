# MegooColab Plan 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A self-hostable MegooColab web platform where admins set up the organization and its users, teams own projects, and people plan work on live agile boards (epics, tasks, subtasks, sprints, burndown, velocity) in the Neon Grid theme.

**Architecture:** Monorepo with a FastAPI backend (`backend/`, async SQLAlchemy 2 + asyncpg, Alembic async migrations, PostgreSQL 17 with pgvector) and a Next.js 16 App Router frontend (`frontend/`, Tailwind v4, Lucide, TanStack Query). Caddy serves both from one origin: `/api/*` → backend, everything else → frontend. Live updates go through PostgreSQL `NOTIFY` → an in-process hub → a cookie-authenticated WebSocket at `/api/ws`, which pushes small "something changed" events that make the frontend refetch.

**Tech Stack:** Python 3.12, uv, FastAPI, SQLAlchemy 2 (asyncio), asyncpg, Alembic, pydantic-settings, pwdlib[argon2], pyotp, aiosmtplib, cryptography (Fernet), pytest + pytest-asyncio + httpx; Node 22, Next.js 16.2, React 19, TypeScript, Tailwind CSS v4 (`@tailwindcss/postcss`), lucide-react, @tanstack/react-query, @dnd-kit/core + @dnd-kit/sortable, react-markdown + remark-gfm, recharts, openapi-typescript, Vitest + Testing Library, Playwright; Docker Compose, Caddy 2.

**Spec:** [docs/brd.md](../../brd.md). This plan covers BRD §11 milestone 1: AUTH-1…7, TEAM-1…3, PROJ-1…9 (except the "needs you" filter in PROJ-7, which comes with the workflow engine in Plan 3), the audit log part of ADM-2, the SMTP and organization parts of ADM-1, NFR-1/4/6/8/10, and §9 Visual design.

### Plan series (each one is its own document, written when the previous one is done)
1. **Foundation** (this plan)
2. Agents: registration, personal access tokens, MCP server (connect-only mode), Go runner skeleton with ACP for Claude Code and Codex, plus the R1 enforcement spike
3. Workflow engine: stages, permission policies, approvals, thread questions and mockups, worktrees, plan → subtasks, automated review, finishing, "needs you"
4. Knowledge Base
5. Memory: learning, ask-the-memory, context injection, dreaming
6. Agent-to-agent questions
7. Git integration, notifications, remaining admin and audit, installer polish

## Global Constraints

- One install = one organization. There is no tenant column anywhere.
- The backend serves everything under `/api`. OpenAPI is at `/api/openapi.json`, and the frontend's TypeScript types are generated from it (NFR-10).
- Roles: `admin`, `manager`, `member`, `viewer`, a single global role per user (BRD §5).
- Project access = admin, or a member of at least one team the project belongs to (BRD §5).
- Accounts: no self-sign-up. Admins **invite by email** or **create directly with a temporary password**, which must be changed at first sign-in (AUTH-1, AUTH-2).
- Invite links expire in 7 days and reset links in 1 hour, and each is single-use. **[Author's call]**
- Password minimum length is 10 characters. **[Author's call]**
- Login lockout: 10 failed attempts within 15 minutes locks the account for 15 minutes. **[Author's call]**
- Sessions: an opaque random token in the `megoo_session` cookie (httpOnly, SameSite=Lax, `Secure` when `COOKIE_SECURE=true`), stored **hashed** (SHA-256) in the database, with a 14-day sliding expiry.
- State-changing requests (POST/PUT/PATCH/DELETE) must carry the header `X-Megoo-Client: web` or they get a 403. This is a CSRF guard that later plans extend to `Authorization: Bearer` tokens.
- Secrets at rest (the SMTP password, and later provider keys) are Fernet-encrypted with a key derived from `SECRET_KEY` (NFR-1).
- Default board columns, in order: **Backlog (before), To Do (before), In Progress (working), In Review (review), Done (done)** (PROJ-3, PROJ-4).
- Column categories: `before`, `working`, `review`, `done`. A project must always keep at least one `before` column and one `done` column.
- Task types: `epic`, `story`, `task`, `bug`, `subtask`. Epics have no parent. A story, task, or bug may have an epic parent. A subtask must have a story, task, or bug parent. Parents must be in the same project (PROJ-1).
- Task keys are `<PROJECTKEY>-<n>`, with `n` sequential per project starting at 1. A project key is 2–10 characters, uppercase A–Z and 0–9, starting with a letter.
- Priorities: `lowest`, `low`, `medium` (default), `high`, `highest`.
- Attachments: stored on local disk under `UPLOAD_DIR`, at most 25 MB each. **[Author's call]**
- Live updates reach viewers within about 2 seconds (NFR-4).
- Neon Grid tokens and fonts, copied exactly from BRD §9:
  - Dark: bg `#0D0221`, card `#170838`, border `#2E1A66`, text `#E9E4FF`, muted `#8F84C0`, cyan `#05D9E8` (with glow), pink `#FF2A6D` (with glow), green `#7CFF6B`.
  - Light: bg `#F6F3FF`, card `#FFFFFF`, border `#D6CCF5`, text `#1A0B3D`, muted `#6B5F99`, cyan `#0090A8`, pink `#D4004F`, green `#1F8F2C`, with no glow and crisp shadows instead.
  - Fonts: Orbitron for headings and the brand name, Share Tech Mono for UI text and IDs.
  - The theme follows the system setting by default and can be toggled by the user.
- Accessibility: text contrast meets WCAG AA in both themes. Glow is never the only way a state is shown. Animations respect `prefers-reduced-motion` (NFR-8).
- Fresh install: `docker compose up` plus first-admin setup in under 15 minutes. Migrations run automatically when the backend starts (NFR-6).

## Review Focus

1. **Two people creating tasks in the same project at the same moment.** Each task must get a unique, gap-free number, never a duplicate key. Tested in Task 10.
2. **Deactivating a user who is signed in and has a board open.** Their next request must return 401, and their open WebSocket must close within 2 seconds (AUTH-4). Tested in Tasks 7 and 14.
3. **Removing someone from a project's only team while they're watching its board.** They must stop receiving that project's live events, and its pages must return 404. No leak through the WebSocket. Tested in Tasks 9 and 14.
4. **Deleting a board column that still has tasks, or that is the last `before`/`done` column.** The first requires a target column and moves the tasks there. The second is refused with 409. Tested in Task 9.
5. **Reusing an invite or reset link, or using an expired one.** It must be rejected with a clear message, and a completed password reset must sign out every existing session. Tested in Task 5.

---

## File Structure

```
.gitignore                       (exists: .superpowers/)
README.md                        install + dev instructions
deploy/
  docker-compose.yml             db (pgvector/pgvector:pg17), backend, frontend, caddy
  docker-compose.dev.yml         db only, port 5433, for local dev + tests
  Caddyfile
  .env.example
backend/
  pyproject.toml  uv.lock  Dockerfile  alembic.ini
  migrations/env.py  migrations/versions/*.py
  app/
    main.py                      create_app(), router registration, lifespan (migrations, event hub)
    core/config.py               Settings (pydantic-settings)
    core/db.py                   Base, engine, get_session
    core/security.py             password + token hashing
    core/crypto.py               Fernet encrypt/decrypt
    core/email.py                Mailer protocol, SmtpMailer, OutboxMailer, get_mailer
    core/events.py               Event, publish(), EventHub
    core/csrf.py                 CSRF header middleware
    audit/models.py service.py router.py
    auth/models.py schemas.py service.py router.py deps.py totp.py
    setup/router.py              first-run admin + org name
    org/models.py router.py      org settings (name, SMTP)
    users/router.py service.py schemas.py
    teams/models.py router.py service.py schemas.py
    projects/models.py router.py service.py schemas.py access.py
    tasks/models.py router.py service.py schemas.py ordering.py
    tasks/activity.py            comments, events, attachments
    sprints/models.py router.py service.py schemas.py
    realtime/router.py           /api/ws
  tests/conftest.py  tests/factories.py  tests/<module>/test_*.py
frontend/
  package.json  next.config.ts  postcss.config.mjs  vitest.config.ts  playwright.config.ts  Dockerfile
  src/proxy.ts                   redirect to /login when no session cookie
  src/app/globals.css            Neon Grid tokens + Tailwind theme
  src/app/layout.tsx             fonts, theme bootstrap script, providers
  src/app/(auth)/setup|login|forgot|reset/[token]|invite/[token]|change-password/page.tsx
  src/app/(app)/layout.tsx       app shell (sidebar, header, theme toggle, realtime)
  src/app/(app)/projects/...     list, new, [key]/board, [key]/backlog, [key]/reports, [key]/settings, [key]/tasks/[number]
  src/app/(app)/teams/...        list, [id]
  src/app/(app)/admin/...        users, settings, audit
  src/app/(app)/settings/profile/page.tsx
  src/lib/api.ts  api-types.ts (generated)  queries.ts  realtime.ts  theme.ts
  src/components/ui/*            Button, Input, Select, Dialog, Badge, Avatar, Markdown
  src/components/board/*         Board, Column, TaskCard
  src/components/task/*          TaskDrawer, TaskFields, ActivityThread, Attachments, Links, Subtasks
  src/components/sprint/*        BacklogList, SprintPanel, BurndownChart, VelocityChart
  e2e/foundation.spec.ts
```

---

### Task 1: Repository scaffolding, backend skeleton, test database

**Files:**
- Create: `deploy/docker-compose.dev.yml`, `backend/pyproject.toml`, `backend/app/main.py`, `backend/app/core/config.py`, `backend/tests/conftest.py`, `backend/tests/test_health.py`, `README.md`

**Interfaces:**
- Produces: `create_app() -> FastAPI` in `app/main.py`; `Settings` with fields `database_url: str`, `secret_key: str`, `cookie_secure: bool = False`, `upload_dir: str = "/data/uploads"`, `public_url: str = "http://localhost:8080"`; `get_settings() -> Settings` (lru_cached). Test fixture `client: httpx.AsyncClient` (ASGITransport, base_url `http://test`, default header `X-Megoo-Client: web`).

- [ ] **Step 1:** Create `deploy/docker-compose.dev.yml` with one service `db` using image `pgvector/pgvector:pg17`, user/password/db `megoo`, port `5433:5432`, and an init script that also creates the database `megoo_test`. Run `docker compose -f deploy/docker-compose.dev.yml up -d`. Expected: `docker compose ps` shows `db` healthy.
- [ ] **Step 2:** `cd backend && uv init --app --python 3.12`, then `uv add fastapi[standard] "sqlalchemy[asyncio]>=2" asyncpg alembic pydantic-settings "pwdlib[argon2]" pyotp aiosmtplib cryptography python-multipart` and `uv add --dev pytest pytest-asyncio httpx`. In `pyproject.toml`, set `[tool.pytest.ini_options] asyncio_mode = "auto"` and `asyncio_default_fixture_loop_scope = "session"`.
- [ ] **Step 3: Write the failing test** `tests/test_health.py`:

```python
async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 4:** Run `uv run pytest tests/test_health.py -v`. Expected: FAIL (no `app.main`).
- [ ] **Step 5:** Implement `Settings`, `create_app()` with `GET /api/health`, `openapi_url="/api/openapi.json"`, `docs_url="/api/docs"`, and the `client` fixture in `conftest.py`. Tests read `TEST_DATABASE_URL`, defaulting to `postgresql+asyncpg://megoo:megoo@localhost:5433/megoo_test`, and set it as `DATABASE_URL` before importing the app.
- [ ] **Step 6:** Run `uv run pytest -v`. Expected: PASS.
- [ ] **Step 7:** In `README.md`, write the dev quick-start: start the db, `uv sync`, `uv run pytest`, `uv run fastapi dev app/main.py`.
- [ ] **Step 8:** Commit: `git add deploy backend README.md && git commit -m "chore: scaffold backend and dev database"`

### Task 2: Database layer, Alembic, crypto, test isolation

**Files:**
- Create: `backend/app/core/db.py`, `backend/app/core/crypto.py`, `backend/alembic.ini`, `backend/migrations/env.py`, `backend/tests/core/test_crypto.py`, `backend/tests/core/test_migrations.py`
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Produces:
  - `Base` (DeclarativeBase with a `uuid.UUID` primary key mixin `IdMixin.id` defaulting to uuid4, and `TimestampMixin.created_at` / `updated_at` as timezone-aware).
  - `engine`, `SessionLocal`, `get_session() -> AsyncIterator[AsyncSession]` (FastAPI dependency; commits on success, rolls back on error).
  - `encrypt(plain: str) -> str`, `decrypt(token: str) -> str` (Fernet key = urlsafe-b64 of SHA-256 of `secret_key`).
  - Fixture `db: AsyncSession`. After each test, every table except `alembic_version` is truncated (`TRUNCATE ... RESTART IDENTITY CASCADE`).

- [ ] **Step 1:** `uv run alembic init -t async migrations`. Point `env.py` at `get_settings().database_url` and `Base.metadata`, and import every `app.*.models` module through `app/models.py` (an aggregator, created here, that later tasks append to).
- [ ] **Step 2: Write failing tests:**

```python
def test_encrypt_roundtrip():
    token = encrypt("smtp-pass")
    assert token != "smtp-pass"
    assert decrypt(token) == "smtp-pass"

async def test_migrations_upgrade_head_is_clean(db):
    # conftest ran `alembic upgrade head` once per session; autogenerate must find no diff
    diff = await run_autogenerate_diff()
    assert diff == []
```

`run_autogenerate_diff()` is a helper in `tests/conftest.py` that uses `alembic.autogenerate.compare_metadata` through `connection.run_sync`.

- [ ] **Step 3:** Run `uv run pytest tests/core -v`. Expected: FAIL.
- [ ] **Step 4:** Implement `db.py` and `crypto.py`, plus the session-scoped fixture that runs `alembic upgrade head` against the test DB, the `db` fixture, and the truncate-after-test fixture (autouse). The app's `get_session` is overridden in tests to use the same engine.
- [ ] **Step 5:** Run `uv run pytest -v`. Expected: PASS.
- [ ] **Step 6:** Commit: `git commit -am "feat(core): async db layer, alembic, crypto"` (add new files first).

### Task 3: Users, password hashing, first-run setup, CSRF guard, audit log

**Files:**
- Create: `backend/app/core/security.py`, `backend/app/core/csrf.py`, `backend/app/auth/models.py`, `backend/app/org/models.py`, `backend/app/audit/models.py`, `backend/app/audit/service.py`, `backend/app/setup/router.py`, `backend/tests/factories.py`, `backend/tests/setup/test_setup.py`, `backend/tests/core/test_csrf.py`, a migration
- Modify: `backend/app/main.py`, `backend/app/models.py`

**Interfaces:**
- Produces:
  - `Role(StrEnum)`: `admin|manager|member|viewer`.
  - `UserStatus(StrEnum)`: `invited|active|deactivated`.
  - `User` model: `email` (unique, lowercased), `name`, `role`, `status`, `password_hash: str|None`, `must_change_password: bool`, `totp_secret_enc: str|None`, `totp_enabled: bool`, `failed_logins: int`, `locked_until: datetime|None`, `last_login_at`.
  - `OrgSettings` (single row, id fixed `1`): `name`, `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password_enc`, `smtp_from`, `smtp_tls: bool`.
  - `AuditLog`: `actor_user_id|None`, `action: str`, `target_type|None`, `target_id|None`, `data: JSONB`, `created_at`.
  - `hash_password(pw: str) -> str`, `verify_password(pw: str, hashed: str) -> bool` (pwdlib `PasswordHash.recommended()`).
  - `new_token() -> str` (`secrets.token_urlsafe(32)`), `hash_token(token: str) -> str` (SHA-256 hex).
  - `audit.record(session, action: str, actor_id: UUID|None = None, target_type: str|None = None, target_id: UUID|None = None, data: dict|None = None) -> None`.
  - Endpoints: `GET /api/setup/status -> {"needs_setup": bool}`; `POST /api/setup {org_name, name, email, password} -> 201 {user}`, allowed only when no users exist (otherwise 409). It creates an active admin and the OrgSettings row, signs the admin in (Task 4 adds the cookie; this task returns 201 only), and records the audit entry `setup.completed`.
  - Factory `make_user(db, role=Role.member, password="correct-horse-1", status=UserStatus.active, **kw) -> User`.

- [ ] **Step 1: Write failing tests:**

```python
async def test_setup_creates_first_admin(client, db):
    assert (await client.get("/api/setup/status")).json() == {"needs_setup": True}
    r = await client.post("/api/setup", json={"org_name": "Acme", "name": "Root", "email": "Root@Acme.io", "password": "correct-horse-1"})
    assert r.status_code == 201
    assert r.json()["user"]["email"] == "root@acme.io" and r.json()["user"]["role"] == "admin"
    assert (await client.get("/api/setup/status")).json() == {"needs_setup": False}

async def test_setup_refused_once_users_exist(client, db):
    await make_user(db, role=Role.admin)
    r = await client.post("/api/setup", json={"org_name": "X", "name": "Y", "email": "y@x.io", "password": "correct-horse-1"})
    assert r.status_code == 409

async def test_setup_rejects_short_password(client):
    r = await client.post("/api/setup", json={"org_name": "A", "name": "B", "email": "b@a.io", "password": "short"})
    assert r.status_code == 422

async def test_mutation_without_client_header_is_forbidden(client):
    r = await client.post("/api/setup", json={}, headers={"X-Megoo-Client": ""})
    assert r.status_code == 403
```

- [ ] **Step 2:** Run `uv run pytest tests/setup tests/core/test_csrf.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement the models, `security.py`, `audit.record`, the CSRF middleware (`csrf.py`: rejects unsafe methods unless `X-Megoo-Client == "web"` or an `Authorization: Bearer` header is present), and the setup router. Generate the migration with `uv run alembic revision --autogenerate -m "users org audit"`.
- [ ] **Step 4:** Run `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: users, first-run setup, csrf guard, audit log`.

### Task 4: Sessions — login, logout, current user, lockout

**Files:**
- Create: `backend/app/auth/schemas.py`, `backend/app/auth/service.py`, `backend/app/auth/router.py`, `backend/app/auth/deps.py`, `backend/tests/auth/test_login.py`
- Modify: `backend/app/auth/models.py` (add `Session`), `backend/app/setup/router.py` (sign in after setup), a migration

**Interfaces:**
- Consumes: `User`, `hash_token`, `new_token`, `verify_password`, `audit.record`.
- Produces:
  - `Session` model: `user_id`, `token_hash` (unique), `expires_at`, `last_seen_at`, `user_agent`.
  - `create_session(db, user, user_agent: str|None) -> str` (returns the raw token), `revoke_user_sessions(db, user_id: UUID) -> None`.
  - `set_session_cookie(response, token)` / `clear_session_cookie(response)`.
  - Dependencies:
    - `current_user(request, db) -> User`: 401 if the session is missing, expired, or for a user who isn't `active`. It slides `expires_at` to now+14 days at most once per hour.
    - `require_roles(*roles: Role)` returns a dependency that gives 403 otherwise.
    - `require_password_ok(user=Depends(current_user)) -> User`: 403 `{"detail": "password_change_required"}` when `must_change_password`. Every non-auth router uses this one instead of `current_user`.
  - Endpoints:
    - `POST /api/auth/login {email, password, totp_code?}`: 200 `{user}` plus cookie. 401 `{"detail":"invalid_credentials"}`. 401 `{"detail":"totp_required"}` when TOTP is enabled and no code was given. 423 `{"detail":"locked"}` while locked.
    - `POST /api/auth/logout`: 204, clears the cookie and deletes the session.
    - `GET /api/auth/me`: `{user}` (UserOut: `id`, `email`, `name`, `role`, `status`, `must_change_password`, `totp_enabled`).
  - Audit actions: `auth.login`, `auth.login_failed`, `auth.locked`.

- [ ] **Step 1: Write failing tests:**

```python
async def test_login_sets_cookie_and_me_returns_user(client, db):
    u = await make_user(db, email="a@x.io")
    r = await client.post("/api/auth/login", json={"email": "A@x.io", "password": "correct-horse-1"})
    assert r.status_code == 200 and "megoo_session" in r.cookies
    me = await client.get("/api/auth/me")
    assert me.json()["user"]["id"] == str(u.id)

async def test_wrong_password_401_and_lockout_after_10(client, db):
    await make_user(db, email="a@x.io")
    for _ in range(10):
        r = await client.post("/api/auth/login", json={"email": "a@x.io", "password": "nope-nope-nope"})
        assert r.status_code == 401
    r = await client.post("/api/auth/login", json={"email": "a@x.io", "password": "correct-horse-1"})
    assert r.status_code == 423

async def test_invited_or_deactivated_cannot_login(client, db):
    await make_user(db, email="d@x.io", status=UserStatus.deactivated)
    r = await client.post("/api/auth/login", json={"email": "d@x.io", "password": "correct-horse-1"})
    assert r.status_code == 401

async def test_logout_invalidates_session(client, db):
    await make_user(db, email="a@x.io")
    await client.post("/api/auth/login", json={"email": "a@x.io", "password": "correct-horse-1"})
    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401

async def test_session_token_stored_hashed(client, db):
    await make_user(db, email="a@x.io")
    r = await client.post("/api/auth/login", json={"email": "a@x.io", "password": "correct-horse-1"})
    raw = r.cookies["megoo_session"]
    rows = (await db.execute(select(Session.token_hash))).scalars().all()
    assert raw not in rows and hash_token(raw) in rows
```

Add a `login(client, user, password="correct-horse-1")` helper to `tests/factories.py`.

- [ ] **Step 2:** Run `uv run pytest tests/auth -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. When the email is unknown, still verify the password against a dummy hash so timing stays the same. The lockout counter resets on a successful login.
- [ ] **Step 4:** Run `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(auth): cookie sessions, login/logout, lockout`.

### Task 5: Invites, direct creation, password change and reset, mailer

**Files:**
- Create: `backend/app/core/email.py`, `backend/tests/auth/test_invites_reset.py`
- Modify: `backend/app/auth/models.py` (add `OneTimeToken`), `backend/app/auth/service.py`, `backend/app/auth/router.py`, `backend/app/users/router.py` (new), `backend/app/users/schemas.py` (new), a migration

**Interfaces:**
- Produces:
  - `OneTimeToken`: `user_id`, `purpose` (`invite|reset`), `token_hash`, `expires_at`, `used_at|None`.
  - `class Mailer(Protocol): async def send(self, to: str, subject: str, body: str) -> None`.
  - `SmtpMailer` reads OrgSettings and decrypts the password. `OutboxMailer` (tests) keeps `.sent: list[tuple[str, str, str]]`.
  - `get_mailer(db) -> Mailer | None` returns None when SMTP isn't configured. Tests override it with an `OutboxMailer`.
  - Admin endpoints (admin only):
    - `POST /api/admin/users/invite {email, name, role}`: 201 `{user, invite_url}`. The user is created with status `invited`, the token is valid 7 days, and an email is sent if a mailer exists. `invite_url` is always returned for copying (AUTH-7).
    - `POST /api/admin/users {email, name, role, temporary_password}`: 201 `{user}` with status active and `must_change_password=True`.
    - `POST /api/admin/users/{id}/reset-link`: 201 `{reset_url}`.
    - Duplicate email gives 409.
  - Public endpoints:
    - `POST /api/auth/accept-invite {token, password}`: 200 `{user}`, activates the user and signs them in.
    - `POST /api/auth/forgot {email}`: always 204, emails a 1-hour reset link if the account exists and is active.
    - `POST /api/auth/reset {token, password}`: 204, revokes all of the user's sessions.
    - Invalid, used, or expired token: 400 `{"detail":"invalid_or_expired_token"}`.
  - Signed in: `POST /api/auth/change-password {current_password, new_password}`: 204, clears `must_change_password`, and revokes the user's other sessions.
  - URLs: `{public_url}/invite/{token}`, `{public_url}/reset/{token}`.
  - Audit actions: `user.invited`, `user.created`, `auth.password_reset`, `auth.password_changed`.

- [ ] **Step 1: Write failing tests:**
  - `test_invite_then_accept_activates_and_signs_in`: admin invites; `outbox.sent[0][0] == email` and the URL from the response is in the body; accept with the token from the URL gives 200; `GET /me` shows status `active`.
  - `test_invite_token_single_use`: a second accept gives 400 `invalid_or_expired_token`.
  - `test_invite_token_expired`: set `expires_at` in the past; accept gives 400.
  - `test_invite_without_smtp_still_returns_url`: with `get_mailer` returning None, still 201 with an `invite_url`.
  - `test_member_cannot_invite`: 403.
  - `test_direct_create_forces_password_change`: log in with the temporary password; `GET /api/teams` gives 403 `password_change_required`; after change-password, 200.
  - `test_reset_revokes_existing_sessions`: log in on client A; forgot, then reset; client A's `/me` gives 401.
  - `test_forgot_unknown_email_is_204_and_sends_nothing`.
  - `test_duplicate_email_409`.
- [ ] **Step 2:** Run `uv run pytest tests/auth/test_invites_reset.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. Use a stub `GET /api/teams` returning `[]` behind `require_password_ok` if Task 8 isn't there yet; Task 8 replaces it.
- [ ] **Step 4:** Run `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(auth): invitations, direct creation, password reset`.

### Task 6: Optional TOTP two-factor login

**Files:**
- Create: `backend/app/auth/totp.py`, `backend/tests/auth/test_totp.py`
- Modify: `backend/app/auth/router.py`, `backend/app/auth/service.py`

**Interfaces:**
- Produces:
  - `POST /api/auth/totp/setup`: 200 `{secret, otpauth_uri}`. The secret is stored encrypted but not yet enabled. Issuer is `MegooColab`, account is the email.
  - `POST /api/auth/totp/enable {code}`: 204, or 400 `invalid_code`.
  - `POST /api/auth/totp/disable {password, code}`: 204.
  - Login with TOTP enabled requires `totp_code`, accepted within a ±1 step window.
  - Audit actions: `auth.totp_enabled`, `auth.totp_disabled`.

- [ ] **Step 1: Write failing tests:** `test_enable_totp_then_login_requires_code`, which uses `pyotp.TOTP(secret).now()`. A login without the code gives 401 `totp_required`, with a wrong code gives 401 `invalid_credentials`, and with the right code gives 200. Also `test_disable_requires_password_and_code`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(auth): optional TOTP`.

### Task 7: Admin user management, organization and SMTP settings, audit API

**Files:**
- Create: `backend/app/core/events.py` (stub: `Event` model + no-op `async def publish(db, event) -> None`; real implementation in Task 14), `backend/app/users/service.py`, `backend/app/org/router.py`, `backend/app/audit/router.py`, `backend/tests/users/test_admin_users.py`, `backend/tests/org/test_org_settings.py`
- Modify: `backend/app/users/router.py`

**Interfaces:**
- Produces:
  - `GET /api/users?q=&status=` (any signed-in user; for assignee pickers): `[UserOut]`.
  - `PATCH /api/admin/users/{id} {name?, role?}`: refuses to demote the last active admin with 409 `last_admin`.
  - `POST /api/admin/users/{id}/deactivate`: 204. Sets status `deactivated`, revokes all sessions, and publishes `Event(type="user.deactivated", user_id=id)` (the publish function arrives in Task 14; until then it calls a no-op `publish` stub defined in `core/events.py`). Deactivating yourself gives 409.
  - `POST /api/admin/users/{id}/reactivate`: 204.
  - `GET /api/org` (any signed-in user): `{name}`.
  - `GET /api/admin/settings`: `{name, smtp: {host, port, user, from, tls, password_set: bool}}`. The password is never returned.
  - `PUT /api/admin/settings` with the same shape plus an optional `smtp.password`.
  - `POST /api/admin/settings/test-email {to}`: 204 or 502 `{"detail": "<smtp error>"}`.
  - `GET /api/admin/audit?action=&actor=&limit=50&before=<iso>`: `[AuditOut]`, newest first.
  - Audit actions: `user.role_changed`, `user.deactivated`, `user.reactivated`, `org.settings_changed`.

- [ ] **Step 1: Write failing tests:**
  - `test_deactivate_revokes_sessions_immediately`: user signed in on client B; admin deactivates; B's `/me` gives 401 (Review Focus 2).
  - `test_cannot_demote_last_admin`.
  - `test_smtp_password_encrypted_and_never_returned`: the DB column != plain text, and GET shows `password_set: true` with no password field.
  - `test_audit_lists_login_and_role_change`.
  - `test_non_admin_forbidden` (parametrized over the admin endpoints).
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(admin): user management, org/SMTP settings, audit API`.

### Task 8: Teams

**Files:**
- Create: `backend/app/teams/models.py`, `backend/app/teams/schemas.py`, `backend/app/teams/service.py`, `backend/app/teams/router.py`, `backend/tests/teams/test_teams.py`, a migration

**Interfaces:**
- Produces:
  - `Team` (`name` unique, `description`) and `TeamMember` (`team_id`, `user_id`, unique pair).
  - `GET /api/teams`: all teams (any signed-in user), each `{id, name, description, member_count, project_count}`.
  - `GET /api/teams/{id}`: `{team, members: [UserOut], projects: [ProjectSummary]}`. TEAM-3 agents are added in Plan 2.
  - `POST /api/teams {name, description}`: admin or manager. A manager creating a team is added as a member automatically.
  - `PATCH /api/teams/{id}` and `DELETE /api/teams/{id}`: admin, or a manager who is a member of the team. Deleting a team that still owns projects gives 409.
  - `PUT /api/teams/{id}/members {user_ids: [UUID]}`: replaces the member set, with the same permission rule. Publishes `Event(type="membership.changed", user_id=...)` for every added or removed user.
  - Service: `user_team_ids(db, user_id) -> set[UUID]`.
  - Audit action: `team.members_changed`.

- [ ] **Step 1: Write failing tests:** `test_manager_creates_team_and_is_member`, `test_member_cannot_create_team`, `test_manager_cannot_edit_team_they_are_not_in`, `test_replace_members`. (`test_delete_team_with_projects_409` lives in Task 9.)
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement. Replace the Task 5 stub.
- [ ] **Step 4:** Run `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: teams`.

### Task 9: Projects, access control, board columns, repositories, labels

**Files:**
- Create: `backend/app/projects/{models,schemas,service,router,access}.py`, `backend/tests/projects/test_projects.py`, `backend/tests/projects/test_columns.py`, a migration

**Interfaces:**
- Consumes: `user_team_ids`, `require_password_ok`, `Role`.
- Produces:
  - Models:
    - `Project`: `key` (unique), `name`, `description`, `sprints_enabled` (default True), `next_task_number` (default 1), `created_by`.
    - `ProjectTeam` (`project_id`, `team_id`).
    - `BoardColumn`: `project_id`, `name`, `position: int`, `category` (`ColumnCategory` StrEnum `before|working|review|done`).
    - `ProjectRepository`: `name`, `url`, `provider` (`github|gitlab|gitea|plain`), `default_branch` (default `main`).
    - `Label`: `project_id`, `name`, `color` (hex), unique per project.
  - `access.py`:
    - `async def accessible_project_ids(db, user) -> set[UUID] | None` (None means all, for admins).
    - `async def get_project_for(db, user, project_ref: str, write: bool = False) -> Project`. `project_ref` is the key or the UUID. Returns 404 when not accessible. Returns 403 when `write` and the user is a viewer.
    - `can_manage_project(user, project, user_team_ids) -> bool`: admin, or a manager in one of the project's teams.
  - Endpoints:
    - `GET /api/projects`: the accessible projects.
    - `POST /api/projects {key, name, description, team_ids}`: admin/manager. The key is validated per Global Constraints and must be unique (409). A manager may only use teams they're a member of. The five default columns are created.
    - `GET/PATCH/DELETE /api/projects/{ref}`. PATCH covers `name`, `description`, `sprints_enabled`, and `team_ids`, and needs manage rights. DELETE is admin only.
    - `GET /api/projects/{ref}/columns`.
    - `POST /api/projects/{ref}/columns {name, category}`: appended at the end.
    - `PATCH /api/projects/{ref}/columns/{id} {name?, category?}`.
    - `PUT /api/projects/{ref}/columns/order {column_ids}`.
    - `DELETE /api/projects/{ref}/columns/{id}?move_to=<column_id>`. 409 `last_before_or_done_column` if it would leave no `before` or no `done` column; this also applies to a category PATCH. 409 `move_to_required` if the column has tasks and no `move_to` was given.
    - `GET/POST/PATCH/DELETE /api/projects/{ref}/repositories[/{id}]` and `/labels[/{id}]`, with manage rights for writes.
    - Every write publishes `Event(type="project.updated" | "columns.updated", project_id=...)`.

- [ ] **Step 1: Write failing tests:**
  - `test_create_project_creates_default_columns`: names and categories in order, exactly as in Global Constraints.
  - `test_project_key_validation` (parametrized: `"P"`, `"1AB"`, `"pay"`, `"TOOLONGKEY1"` give 422, `"PAY"` gives 201).
  - `test_access_follows_team_membership`: a member outside the team gets 404 on GET and the project is missing from the list; after being added to the team, 200 (Review Focus 3, HTTP half).
  - `test_viewer_cannot_write` and `test_manager_outside_teams_cannot_edit`.
  - `test_cannot_delete_last_done_column` and `test_cannot_recategorize_last_before_column`.
  - `test_reorder_columns` and `test_delete_team_with_projects_409`.
  - (`test_delete_column_with_tasks_requires_move_to` lives in Task 10, once tasks exist.)
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: projects, access, board columns, repos, labels`.

### Task 10: Tasks — create, read, update, numbering, hierarchy, filters

**Files:**
- Create: `backend/app/tasks/{models,schemas,service,router}.py`, `backend/tests/tasks/test_tasks.py`, a migration

**Interfaces:**
- Consumes: `get_project_for`, `BoardColumn`, `Label`.
- Produces:
  - `TaskType` and `Priority` StrEnums per Global Constraints.
  - `Task`: `project_id`, `number`, `type`, `title`, `description_md`, `column_id`, `position: float`, `priority`, `story_points: int|None`, `due_date: date|None`, `assignee_user_id|None`, `reporter_id`, `parent_id|None`, `sprint_id|None`, `completed_at|None`. Unique (`project_id`, `number`).
  - `task_labels` and `task_watchers` association tables.
  - `TaskOut`: all of the above plus `key`, `labels: [LabelOut]`, `subtask_count`, `subtask_done_count`, `column_category`.
  - `create_task(db, user, project, data: TaskCreate) -> Task`. It takes the number via `UPDATE projects SET next_task_number = next_task_number + 1 ... RETURNING` and places the task at the end of its column. The default column is the first `before` column. When the target column is `done`, `completed_at` is set. The reporter becomes a watcher.
  - `update_task(db, user, task, data: TaskUpdate) -> Task`.
  - Endpoints:
    - `POST /api/projects/{ref}/tasks`.
    - `GET /api/projects/{ref}/tasks?type=&assignee=&label=&epic=&sprint=<id|backlog|active>&column=&q=` (the `q` filter does `ILIKE` on title).
    - `GET /api/tasks/{key}`, e.g. `PAY-12`.
    - `PATCH /api/tasks/{key}`.
    - `DELETE /api/tasks/{key}`: reporter, or project manage rights. Subtasks cascade, and an epic's children get `parent_id = NULL`.
    - The assignee must have access to the project (422 `assignee_no_access`).
    - Hierarchy violations give 422 `invalid_parent`.
    - Viewers get 403 on writes.
  - Events published: `task.created`, `task.updated`, `task.deleted` (`project_id`, `task_id`).

- [ ] **Step 1: Write failing tests:**

```python
async def test_concurrent_creates_get_unique_sequential_numbers(app_clients, project):
    # 20 creates through 4 separately-logged-in clients, gathered concurrently
    results = await asyncio.gather(*[c.post(f"/api/projects/{project.key}/tasks", json={"title": f"t{i}", "type": "task"}) for i, c in enumerate(app_clients * 5)])
    numbers = sorted(r.json()["number"] for r in results)
    assert numbers == list(range(1, 21))      # Review Focus 1
```

Also:
  - `test_key_format` (`PAY-1`).
  - `test_default_column_is_first_before_column`.
  - `test_subtask_requires_non_epic_parent` and `test_epic_cannot_have_parent` (both 422 `invalid_parent`).
  - `test_parent_must_be_same_project`.
  - `test_assignee_without_access_422`.
  - `test_filters` (by label, assignee, epic, and `sprint=backlog`).
  - `test_viewer_cannot_create`.
  - `test_delete_column_with_tasks_requires_move_to` (Review Focus 4; moves the tasks when `move_to` is given).
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: tasks with per-project numbering and hierarchy`.

### Task 11: Moving tasks and ordering, links, watchers

**Files:**
- Create: `backend/app/tasks/ordering.py`, `backend/tests/tasks/test_move.py`, `backend/tests/tasks/test_links.py`
- Modify: `backend/app/tasks/models.py` (add `TaskLink`, `TaskEvent`), `backend/app/tasks/service.py` (add `record_event`; record `created`, `assigned`, `field_changed` from create/update), `backend/app/tasks/router.py`, a migration

**Interfaces:**
- Produces:
  - `position_between(before: float|None, after: float|None) -> float`: the midpoint. With None on one side it gives ±1024 from the other side. With both None it gives 1024.0.
  - `needs_rebalance(a: float, b: float) -> bool`: true when `abs(a - b) < 1e-6`. In that case the column is renumbered to 1024, 2048, and so on, in the same transaction.
  - `TaskEvent`: `task_id`, `actor_user_id|None`, `kind: str`, `data: JSONB`. Kinds in this plan: `created`, `status_changed {from_column, to_column, to_category}`, `assigned {from, to}`, `field_changed {field, from, to}`, `sprint_changed {from, to}` (Task 13). Later plans add kinds.
  - `record_event(db, task, actor_id: UUID|None, kind: str, data: dict) -> TaskEvent`.
  - `POST /api/tasks/{key}/move {column_id, before_key?: str, after_key?: str}`. `before_key` is the card directly above the drop spot, `after_key` the card directly below. It sets `completed_at` when entering a `done` category column and clears it when leaving one. It records `status_changed` and publishes `task.updated`.
  - `TaskLink`: `source_id`, `target_id`, `kind` (`blocks|relates`), unique triple.
  - `POST /api/tasks/{key}/links {target_key, kind}` and `DELETE /api/tasks/{key}/links/{id}`.
  - `TaskOut.links` lists `{id, kind: "blocks"|"blocked_by"|"relates", task: {key, title, column_category}}`. `blocked_by` is the inverse view of `blocks`.
  - `PUT /api/tasks/{key}/watch` and `DELETE /api/tasks/{key}/watch`.

- [ ] **Step 1: Write failing tests:** `test_position_between_cases` (pure unit test), `test_move_between_two_cards_orders_correctly`, `test_move_into_done_sets_completed_at_and_out_clears_it`, `test_many_moves_trigger_rebalance_and_keep_order` (60 moves into the same gap; the final order matches expectations), `test_blocks_shows_blocked_by_on_target`, `test_self_link_422`, `test_watch_unwatch`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: task moves, ordering, links, watchers`.

### Task 12: Comments, events, activity thread, attachments

**Files:**
- Create: `backend/app/tasks/activity.py`, `backend/tests/tasks/test_activity.py`, `backend/tests/tasks/test_attachments.py`
- Modify: `backend/app/tasks/models.py` (add `Comment`, `Attachment`), a migration

**Interfaces:**
- Consumes: `TaskEvent`, `record_event` (Task 11).
- Produces:
  - `Comment`: `task_id`, `author_user_id`, `body_md`, `edited_at|None`.
  - `Attachment`: `task_id`, `filename`, `content_type`, `size`, `storage_key`, `uploaded_by`.
  - Endpoints:
    - `GET /api/tasks/{key}/activity?before=<iso>&limit=50`: `[{type: "comment"|"event", at, actor: UserOut|None, ...}]`, newest last.
    - `POST /api/tasks/{key}/comments {body_md}`, `PATCH /api/comments/{id}` (author only), and `DELETE /api/comments/{id}` (author or admin).
    - `POST /api/tasks/{key}/attachments` (multipart): 413 over 25 MB. The file is saved under `UPLOAD_DIR/<task_id>/<uuid>`.
    - `GET /api/attachments/{id}`: streams with `Content-Disposition: attachment`, after an access check.
    - `DELETE /api/attachments/{id}`.
  - Events published: `comment.created`, `task.updated` (for attachment changes).

- [ ] **Step 1: Write failing tests:** `test_activity_merges_comments_and_events_in_order`, `test_comment_edit_only_by_author`, `test_upload_and_download_attachment_roundtrip`, `test_attachment_over_limit_413`, `test_attachment_download_requires_project_access` (404 for an outsider), `test_attachment_filename_path_traversal_is_neutralized` (filename `../../etc/passwd` is stored as a plain name and saved under the uuid key).
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement. Set `UPLOAD_DIR` to a `tmp_path` in tests.
- [ ] **Step 4:** Run `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: task activity thread, comments, attachments`.

### Task 13: Sprints, burndown, velocity

**Files:**
- Create: `backend/app/sprints/{models,schemas,service,router}.py`, `backend/tests/sprints/test_sprints.py`, a migration
- Modify: `backend/app/tasks/service.py` (call `record_snapshot` after changes that touch an active sprint's tasks)

**Interfaces:**
- Produces:
  - `SprintState` StrEnum: `planned|active|completed`.
  - `Sprint`: `project_id`, `name`, `goal`, `start_date`, `end_date`, `state`, `completed_at`, `committed_points`, `completed_points`.
  - `SprintSnapshot`: `sprint_id`, `day: date`, `total_points`, `remaining_points`, unique (`sprint_id`, `day`).
  - `record_snapshot(db, sprint_id: UUID) -> None`: upserts today's row. Total is the sum of points of the sprint's non-epic, non-subtask tasks. Remaining is the same sum over tasks not in a `done` column. Null points count as 0.
  - Endpoints (all 409 `sprints_disabled` when the project has sprints off):
    - `GET /api/projects/{ref}/sprints`.
    - `POST /api/projects/{ref}/sprints {name, goal, start_date, end_date}`.
    - `PATCH /api/sprints/{id}`.
    - `POST /api/sprints/{id}/start`: 409 `active_sprint_exists`. Sets `committed_points` and records a snapshot.
    - `POST /api/sprints/{id}/complete {move_open_to: "backlog" | <sprint_id>}`: sets `completed_points` and moves unfinished tasks.
    - `PUT /api/tasks/{key}/sprint {sprint_id|null}`: records a `sprint_changed` event.
    - `GET /api/sprints/{id}/burndown`: `[{day, remaining_points, ideal_points}]`, covering every day from start to min(today, end). Days with no snapshot carry forward the previous value. Ideal is a straight line from `committed_points` to 0.
    - `GET /api/projects/{ref}/velocity?last=6`: `[{sprint_id, name, committed_points, completed_points}]`.
  - Events published: `sprint.updated`.

- [ ] **Step 1: Write failing tests:** `test_only_one_active_sprint`, `test_burndown_forward_fills_and_ideal_line` (freeze dates with a `today` parameter injected into the service, `service.today = lambda: date(...)`), `test_complete_moves_open_tasks_to_backlog`, `test_complete_moves_open_tasks_to_next_sprint`, `test_velocity_lists_completed_sprints_newest_last`, `test_sprints_disabled_409`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: sprints, burndown, velocity`.

### Task 14: Live updates — event publishing and WebSocket

**Files:**
- Create: `backend/app/realtime/router.py`, `backend/tests/realtime/test_ws.py`
- Modify: `backend/app/core/events.py` (replace the stub), `backend/app/main.py` (lifespan starts and stops the `EventHub`)

**Interfaces:**
- Produces:
  - `class Event(BaseModel)`: `type: str`, `project_id: UUID|None = None`, `task_id: UUID|None = None`, `user_id: UUID|None = None`.
  - `async def publish(db: AsyncSession, event: Event) -> None` runs `SELECT pg_notify('megoo_events', :json)`. Because NOTIFY is transactional, the event is delivered only if the transaction commits.
  - `class EventHub`: `start(dsn: str)` opens a dedicated asyncpg connection with `add_listener`; `subscribe() -> asyncio.Queue[Event]`; `unsubscribe(q)`; `stop()`. It reconnects with backoff if the listener connection drops.
  - `WS /api/ws`:
    - Authenticated by the session cookie; closes with code 4401 if unauthenticated.
    - Sends JSON events only when `event.project_id` is in the connection's accessible project set, or when `event.user_id` is the connection's own user.
    - Recomputes the accessible set when it receives `membership.changed` for its user, and also on any `project.updated` (team changes).
    - Closes with code 4401 when it receives `user.deactivated` for its user.
    - Sends `{"type":"ping"}` every 25 s.

- [ ] **Step 1: Write failing tests** (use FastAPI `TestClient` with `websocket_connect`; the engine uses `NullPool` in tests to avoid sharing connections across event loops):
  - `test_ws_rejects_without_session` (close code 4401).
  - `test_ws_receives_task_created_for_accessible_project`.
  - `test_ws_does_not_receive_other_projects_events`.
  - `test_ws_stops_receiving_after_removed_from_team` (Review Focus 3).
  - `test_ws_closes_on_deactivation_within_2s` (Review Focus 2).
  - `test_publish_inside_rolled_back_transaction_is_not_delivered`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement. Swap every earlier `publish` stub call for the real function (the signature is unchanged).
- [ ] **Step 4:** Run `uv run pytest -v`. Expected: PASS (full backend suite).
- [ ] **Step 5:** Commit: `feat: realtime events over postgres notify + websocket`.

### Task 15: Frontend scaffold — Neon Grid theme, fonts, API client, generated types

**Files:**
- Create: `frontend/` (via `create-next-app`), `frontend/src/app/globals.css`, `frontend/src/app/layout.tsx`, `frontend/src/lib/theme.ts`, `frontend/src/lib/api.ts`, `frontend/src/lib/queries.ts`, `frontend/src/proxy.ts`, `frontend/src/components/ui/{Button,Input,Select,Dialog,Badge,Avatar,Markdown}.tsx`, `frontend/src/components/ThemeToggle.tsx`, `frontend/vitest.config.ts`, `frontend/src/lib/__tests__/api.test.ts`, `frontend/src/components/__tests__/ThemeToggle.test.tsx`
- Modify: `deploy/docker-compose.dev.yml` (add a `caddy` service that proxies `localhost:8080`: `/api/*` → `host.docker.internal:8000`, everything else → `host.docker.internal:3000`), `deploy/Caddyfile.dev`

**Interfaces:**
- Produces:
  - `api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T>` always sends `credentials: "include"` and `X-Megoo-Client: web`. It throws `ApiError { status: number; detail: string }`. On 401 outside `/login|/setup|/invite|/reset|/forgot`, it redirects to `/login?next=<path>`. On 403 `password_change_required`, it redirects to `/change-password`.
  - `npm run gen:api` runs `openapi-typescript http://localhost:8080/api/openapi.json -o src/lib/api-types.ts`. The generated file is committed.
  - `qk`, the query-key factory: `qk.me()`, `qk.projects()`, `qk.project(ref)`, `qk.columns(ref)`, `qk.tasks(ref, filters)`, `qk.task(key)`, `qk.activity(key)`, `qk.sprints(ref)`, `qk.burndown(id)`, `qk.velocity(ref)`, `qk.teams()`, `qk.team(id)`, `qk.users()`.
  - Theme:
    - `type ThemePref = "system" | "dark" | "light"`.
    - `getThemePref()` / `setThemePref(p)` use `localStorage`, wrapped in try/catch.
    - `applyTheme(p)` sets `document.documentElement.dataset.theme` to `"dark"|"light"`.
    - An inline script in `layout.tsx` applies the theme before paint.
  - Tailwind: `@custom-variant dark (&:where([data-theme=dark], [data-theme=dark] *));`.
  - `@theme` tokens: `--color-bg`, `--color-card`, `--color-line`, `--color-fg`, `--color-muted`, `--color-cyan`, `--color-pink`, `--color-green`, `--font-display` (Orbitron), and `--font-mono` (Share Tech Mono). Their values switch per `[data-theme]` with the exact hex values from Global Constraints. Glow utilities `glow-cyan` and `glow-pink` are no-ops in light mode and under `prefers-reduced-motion`.
  - Fonts load via `next/font/google` (`Orbitron` 500/700, `Share_Tech_Mono` 400).
  - `proxy.ts` redirects to `/login` when there is no `megoo_session` cookie, for every path except the auth routes, `/_next`, and `/api`.

- [ ] **Step 1:** `npx create-next-app@16.2 frontend --ts --tailwind --app --src-dir --eslint --use-npm`. Then `npm i lucide-react @tanstack/react-query @dnd-kit/core @dnd-kit/sortable react-markdown remark-gfm recharts` and `npm i -D vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/user-event openapi-typescript @playwright/test`. Set `rewrites` in `next.config.ts` so `/api/:path*` goes to `${process.env.BACKEND_URL ?? "http://localhost:8000"}/api/:path*` for `next dev` without Caddy (WebSocket in dev still goes through Caddy on port 8080).
- [ ] **Step 2: Write failing tests:**
  - `api.test.ts`: sends the `X-Megoo-Client` header and credentials; throws `ApiError` with the server's `detail`; redirects on 401 (mock `fetch` and `location.assign`).
  - `ThemeToggle.test.tsx`: cycles system → dark → light; sets `data-theme`; survives `localStorage` throwing.
- [ ] **Step 3:** Run `npx vitest run`. Expected: FAIL.
- [ ] **Step 4:** Implement the files listed above. Build a token preview at `/dev/tokens` (dev only) showing all colors in both themes.
- [ ] **Step 5:** Run `npx vitest run` and `npm run build`. Expected: PASS, and the build succeeds.
- [ ] **Step 6:** Commit: `feat(frontend): scaffold, Neon Grid theme, api client`.

### Task 16: Sign-in pages — setup, login, forgot/reset, accept invite, forced password change

**Files:**
- Create: `frontend/src/app/(auth)/layout.tsx` (centered neon card on grid background), `setup/page.tsx`, `login/page.tsx`, `forgot/page.tsx`, `reset/[token]/page.tsx`, `invite/[token]/page.tsx`, `change-password/page.tsx`, `frontend/src/app/(auth)/__tests__/login.test.tsx`

**Interfaces:**
- Consumes: `api`, the generated types, and the endpoints from Tasks 3–6.
- Produces:
  - `/login` redirects to `/setup` when `needs_setup`. It shows the TOTP code field after a 401 `totp_required`, then signs in and goes to `next` or `/projects`. Error copy: "Wrong email or password." for `invalid_credentials`, and "Too many attempts. Try again in 15 minutes." for `locked`.
  - Reset and invite pages show "This link is invalid or has expired. Ask your admin for a new one." for `invalid_or_expired_token`.
  - Password fields enforce 10 or more characters on the client too.

- [ ] **Step 1: Write failing tests:** `login.test.tsx` covers the TOTP field appearing after `totp_required`, the error copy for `invalid_credentials` and `locked`, and the redirect to `next`.
- [ ] **Step 2:** Run `npx vitest run`. Expected: FAIL.
- [ ] **Step 3:** Implement all six pages.
- [ ] **Step 4:** Run `npx vitest run`. Expected: PASS. Manually: the full stack in dev, a fresh DB, setup, sign out, sign in.
- [ ] **Step 5:** Commit: `feat(frontend): auth pages`.

### Task 17: App shell, admin pages, profile

**Files:**
- Create: `frontend/src/app/(app)/layout.tsx`, `frontend/src/components/shell/{Sidebar,Header}.tsx`, `frontend/src/lib/realtime.ts`, `(app)/admin/users/page.tsx`, `(app)/admin/settings/page.tsx`, `(app)/admin/audit/page.tsx`, `(app)/settings/profile/page.tsx`, `frontend/src/lib/__tests__/realtime.test.ts`

**Interfaces:**
- Produces:
  - Shell: the brand "MEGOO**COLAB**" in Orbitron (cyan with a pink suffix, as in the mockup); a sidebar with Projects, Teams, and Admin (admins only); a header with breadcrumbs, the theme toggle, and the user menu (Profile, Sign out).
  - `useRealtime()`, mounted once in the shell:
    - Connects to `/api/ws` and reconnects with backoff (1 s → 30 s).
    - Maps events to invalidations: `task.*` → `qk.tasks(project)` + `qk.task(id)` + `qk.activity`; `comment.created` → `qk.activity`; `columns.updated` → `qk.columns`; `project.updated` → `qk.projects()` + `qk.project`; `sprint.updated` → `qk.sprints` + `qk.burndown` + `qk.velocity`; `membership.changed` → everything.
    - On close code 4401, navigates to `/login`.
    - Events carry IDs while queries are keyed by `ref`/`key`, so the hook keeps a small map from project id to key, filled from `qk.projects()`, and invalidates by prefix (e.g. `["tasks"]`) when the map is missing an id.
  - Admin users page:
    - A table of users with status and role badges.
    - "Invite user" and "Create user" dialogs; the invite dialog shows the invite URL with a copy button.
    - Role select, deactivate/reactivate, and "Copy reset link".
  - Admin settings page: org name, SMTP form, and "Send test email".
  - Audit page: a filterable list.
  - Profile page: name, change password, and TOTP setup (QR code drawn from `otpauth_uri` using the `qrcode` npm package, then confirm the code) and disable.

- [ ] **Step 1: Write failing tests:** `realtime.test.ts` uses a mock WebSocket to check that `task.updated` invalidates the right keys and that close code 4401 redirects to login.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement. Add the `qrcode` package.
- [ ] **Step 4:** Run `npx vitest run`. Expected: PASS. Manually: invite a user without SMTP, copy the link, accept it in a private window.
- [ ] **Step 5:** Commit: `feat(frontend): app shell, admin, profile, realtime`.

### Task 18: Teams pages

**Files:**
- Create: `(app)/teams/page.tsx`, `(app)/teams/[id]/page.tsx`, `frontend/src/components/team/MemberPicker.tsx`

**Interfaces:**
- Produces: the teams list with member and project counts and a "New team" button (admin/manager); a team page with members (and the MemberPicker for anyone with edit rights) and projects. An agents section placeholder is hidden until Plan 2.

- [ ] **Step 1:** Write a failing test `MemberPicker.test.tsx`: search filters users, and selecting toggles membership; the saved payload equals the selected ids.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npx vitest run`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(frontend): teams`.

### Task 19: Project list, creation, and settings

**Files:**
- Create: `(app)/projects/page.tsx`, `(app)/projects/new/page.tsx`, `(app)/projects/[key]/layout.tsx` (project tabs: Board, Backlog, Reports, Settings; Backlog and Reports are hidden when sprints are off), `(app)/projects/[key]/settings/page.tsx`, `frontend/src/components/project/{ColumnEditor,RepoEditor,LabelEditor}.tsx`, `frontend/src/components/project/__tests__/ColumnEditor.test.tsx`

**Interfaces:**
- Produces:
  - Settings tabs: General (name, description, sprints toggle, teams); Columns (rename, category select with the four categories, drag to reorder, add, delete); Repositories; Labels.
  - Deleting a column that has tasks opens a "Move its tasks to…" select. The API's 409 `last_before_or_done_column` shows: "A project needs at least one 'before work' column and one 'done' column."

- [ ] **Step 1: Write failing tests** for `ColumnEditor`: the delete dialog asks for a target when `task_count > 0`; the 409 message is shown; reordering sends `column_ids` in the new order.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement. Add `task_count` to the columns endpoint response (backend: extend `GET /columns` with a count, plus a test in `tests/projects/test_columns.py`).
- [ ] **Step 4:** Run the backend and frontend tests. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(frontend): projects and settings`.

### Task 20: Kanban board with drag and drop and live updates

**Files:**
- Create: `(app)/projects/[key]/board/page.tsx`, `frontend/src/components/board/{Board,Column,TaskCard,BoardFilters,QuickCreate}.tsx`, `frontend/src/components/board/moveTarget.ts`, `frontend/src/components/board/__tests__/moveTarget.test.ts`, `frontend/src/components/board/__tests__/TaskCard.test.tsx`

**Interfaces:**
- Consumes: `POST /api/tasks/{key}/move`, `GET /api/projects/{ref}/tasks`, `GET /columns`.
- Produces:
  - `moveTarget(columnTasks: TaskOut[], overIndex: number, draggedKey: string): { before_key?: string; after_key?: string }`. It's pure and computes the neighbors of the drop spot without the dragged card.
  - Board shows:
    - Sprints on: the active sprint's tasks, or an empty state "No active sprint — plan one in Backlog."
    - Sprints off: all tasks.
    - Epics and subtasks are excluded in both cases.
  - Card shows the key in Share Tech Mono, the title, priority icon (Lucide), labels, points, assignee avatar, and subtask progress "n/m". The active/dragging card glows cyan.
  - Optimistic move with rollback on error.
  - Filters: assignee, label, epic, and text search.
  - Quick-create at the top of each column.
  - Clicking a card opens the task drawer (Task 21) via `?task=PAY-12`.
  - Column header shows the name and count.

- [ ] **Step 1: Write failing tests:** `moveTarget` cases (top of column, bottom, middle, empty column, moving within the same column downward); `TaskCard` renders the key, points, and "2/5"; it has no glow class in light theme and no animation class under reduced motion.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement with `@dnd-kit/core` + `@dnd-kit/sortable`, with keyboard dragging enabled (accessibility).
- [ ] **Step 4:** Run `npx vitest run`. Expected: PASS. Manually: two browsers on the same board; a move in one shows in the other within 2 s.
- [ ] **Step 5:** Commit: `feat(frontend): live kanban board`.

### Task 21: Task drawer — fields, Markdown, thread, attachments, links, subtasks

**Files:**
- Create: `frontend/src/components/task/{TaskDrawer,TaskFields,ActivityThread,CommentBox,Attachments,Links,Subtasks}.tsx`, `(app)/projects/[key]/tasks/[number]/page.tsx` (full-page variant for deep links), `frontend/src/components/task/__tests__/ActivityThread.test.tsx`

**Interfaces:**
- Produces:
  - Drawer: an editable title; Markdown description (edit/preview, rendered by `Markdown` with `remark-gfm` and no raw HTML); type, column, priority, points, due date, assignee, labels, epic/parent, and sprint fields; watch toggle; links (add by key, shown as blocks/blocked by/relates); subtasks list with quick-add; attachments (upload, download, delete); activity thread (comments and events, newest at the bottom, "load earlier"); delete task.
  - `ActivityThread` renders unknown event kinds generically as "\<actor\> \<kind\>", so later plans' event kinds degrade gracefully.

- [ ] **Step 1: Write failing tests:** `ActivityThread` renders a comment, a `status_changed` event as "moved to In Review", an `assigned` event, and an unknown kind generically; Markdown does not render a raw `<script>` tag.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npx vitest run`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(frontend): task drawer and activity thread`.

### Task 22: Backlog, sprint planning, reports

**Files:**
- Create: `(app)/projects/[key]/backlog/page.tsx`, `(app)/projects/[key]/reports/page.tsx`, `frontend/src/components/sprint/{SprintPanel,BacklogList,StartSprintDialog,CompleteSprintDialog,BurndownChart,VelocityChart}.tsx`, `frontend/src/components/sprint/__tests__/CompleteSprintDialog.test.tsx`

**Interfaces:**
- Produces:
  - Backlog page: the active sprint and planned sprints as panels, each with a task list, total points, and start/complete buttons; the backlog list below. Tasks drag between panels (`PUT /api/tasks/{key}/sprint`). Epics are shown as a filter sidebar.
  - Complete dialog: "Move N open tasks to: Backlog | \<next planned sprint\>".
  - Reports page:
    - Burndown for the active sprint, or a selected completed sprint: remaining line in cyan, ideal line dashed in muted color.
    - Velocity bars for committed vs completed: muted vs cyan.
    - Both charts use Recharts with the theme tokens, readable in both themes, with an accessible data table toggle.

- [ ] **Step 1: Write failing tests:** `CompleteSprintDialog` lists the next planned sprint as an option and sends the `move_open_to` value.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npx vitest run`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(frontend): backlog, sprints, reports`.

### Task 23: Production deployment and end-to-end smoke test

**Files:**
- Create: `backend/Dockerfile`, `frontend/Dockerfile`, `deploy/docker-compose.yml`, `deploy/Caddyfile`, `deploy/.env.example`, `frontend/playwright.config.ts`, `frontend/e2e/foundation.spec.ts`
- Modify: `backend/app/main.py` (lifespan runs `alembic upgrade head` before starting the hub), `README.md` (install guide)

**Interfaces:**
- Produces:
  - Compose services:
    - `db`: `pgvector/pgvector:pg17`, volume `pgdata`.
    - `backend`: uvicorn with 1 worker; volume `uploads` at `/data/uploads`; env from `.env`.
    - `frontend`: `next start`, standalone output.
    - `caddy`: ports `80`/`443`, with `SITE_ADDRESS` in env. `localhost` → port 8080 over HTTP for trials. A real domain gets automatic TLS, with `COOKIE_SECURE=true`.
  - `.env.example`: `SITE_ADDRESS`, `PUBLIC_URL`, `SECRET_KEY` (with the instruction "generate with `openssl rand -hex 32`"), `POSTGRES_PASSWORD`, `COOKIE_SECURE`.
  - The backend refuses to start if `SECRET_KEY` is unset or still the example value, and says so in the log.

- [ ] **Step 1: Write the failing e2e test** `e2e/foundation.spec.ts`, against `http://localhost:8080`:
  1. Setup creates the admin.
  2. The admin invites a member (copies the URL) and creates team "Core" with both users.
  3. The admin creates project `PAY` for "Core".
  4. The admin creates task "Sync orders" (key `PAY-1`).
  5. A second browser context accepts the invite and opens the PAY board.
  6. The admin drags `PAY-1` to In Progress.
  7. The member's board shows `PAY-1` in In Progress within 2 seconds.
  8. The member comments, and the admin's open drawer shows the comment.
  9. The admin removes the member from "Core"; the member's next navigation to PAY shows "Project not found".
- [ ] **Step 2:** `docker compose -f deploy/docker-compose.yml --env-file deploy/.env.example up -d --build` (with a test `SECRET_KEY` override), then `npx playwright test`. Expected: FAIL until the Dockerfiles and compose file work.
- [ ] **Step 3:** Implement the Dockerfiles, compose, Caddyfile, migrations on startup, the `SECRET_KEY` guard, and the README install section, which covers: copy `.env.example` → `.env`, set the secrets, `docker compose up -d`, open the site, complete setup, configure SMTP (optional), and upgrade with `docker compose pull && docker compose up -d`.
- [ ] **Step 4:** Rebuild, then run `npx playwright test`. Expected: PASS. Time a fresh install from an empty machine with images built, from `cp .env.example` to setup completed. Expected: under 15 minutes (NFR-6).
- [ ] **Step 5:** Commit: `feat(deploy): docker compose, caddy, e2e smoke test`.

---

## Spec coverage (Plan 1)

| BRD item | Task |
|---|---|
| AUTH-1, AUTH-2 | 3, 5 |
| AUTH-3 | 5, 6 |
| AUTH-4 | 7, 14 (agent tokens/runners: Plan 2) |
| AUTH-5 | 3 (local `User` record with password nullable; external identities attach later) |
| AUTH-6 | Plan 2 |
| AUTH-7 | 5, 7 |
| TEAM-1, TEAM-2 | 8, 9 |
| TEAM-3 | 8, 18 (agents: Plan 2) |
| PROJ-1, PROJ-5 | 10, 11, 12, 21 (agent assignee: Plan 2) |
| PROJ-2 | 13, 22 |
| PROJ-3, PROJ-4 | 9, 19, 20 |
| PROJ-6 | 12, 21 |
| PROJ-7 | 10, 20 ("needs you": Plan 3) |
| PROJ-8 | 14, 17, 20 |
| PROJ-9 | 9, 19 |
| ADM-1 (org, SMTP) | 7, 17 |
| ADM-2 (audit) | 3, 7, 17 |
| NFR-1 | 2, 4, 7 |
| NFR-4 | 14, 20, 23 |
| NFR-6 | 23 |
| NFR-8 | 15, 20, 22 |
| NFR-10 | 1, 15 |
| §9 Visual design | 15, 16, 17, 20 |
