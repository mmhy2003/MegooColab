# Releases and Update Notices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Versioned releases of MegooColab (Docker images) and the runner (binaries) published by GitHub Actions on every push to `main` that carries a new version, servers that install and update from those images, and in-app notices when either is out of date.

**Architecture:** A small release tool (`tools/release/versions.py`) owns the version rules (files agree, a changed product must be bumped, which products need a release, the Scoop manifest); `release.yml` calls it, reuses CI as its gate, smoke-starts the stack from the new images, then publishes. The backend learns the latest versions from GitHub's releases API in a worker job, stores them in org settings, and serves them at `GET /api/updates`; agents carry their live runner's version so the frontend can show the header pill (admins) and the runner arrow.

**Tech Stack:** GitHub Actions, Docker Buildx/GHCR, GoReleaser; Python 3.12 (FastAPI, httpx, SQLAlchemy/Alembic, pytest); Next 16 / React 19 / TanStack Query / vitest.

**Spec:** `docs/superpowers/specs/2026-10-29-releases-and-update-notices-design.md`

## Global Constraints

- Work on branches off `develop`, merged into `develop`. Nothing in this plan touches `main` or bumps a version; the first release (0.1.0 / runner 0.1.0) is a later, separate step the owner asks for.
- Repository `mmhy2003/MegooColab`. Images `ghcr.io/mmhy2003/megoocolab-backend` (backend and worker) and `ghcr.io/mmhy2003/megoocolab-frontend`, tagged `<VERSION>` and `latest`, for `linux/amd64,linux/arm64`. Release tags `v<X.Y.Z>` (title `MegooColab <X.Y.Z>`) and `runner-v<X.Y.Z>` (title `Runner <X.Y.Z>`).
- Version files: `VERSION` (root, `0.1.0`), equal to `backend/pyproject.toml` and `frontend/package.json` versions; `runner/VERSION` (`0.1.0`). Release notes: `docs/releases/v<X.Y.Z>.md`, `docs/releases/runner-v<X.Y.Z>.md`.
- A release version is exactly `X.Y.Z` (an optional leading `v` is stripped); anything else (`dev`, `0.1.0-dev+abc`, `1.0`) is "not a release" and never triggers a notice. Comparison is numeric per part.
- Runner binary stays `megoocolab-runner` (`.exe` on Windows); archive names unchanged (`megoocolab-runner_<version>_<os>_<arch>`, `.zip` on Windows, `checksums.txt`).
- Backend settings: `APP_VERSION` (default `dev`, baked into the backend image by the release build), `UPDATE_CHECK` (default `true`). The check runs every 6 hours and once when the worker starts.
- Copy, verbatim: pill text `Update`; pill aria-label `Update available: MegooColab {latest}`; popover `MegooColab {latest}` / `You're on {current}.` / links `What's new`, `How to update` (→ `https://github.com/mmhy2003/MegooColab/blob/main/docs/install.md#12-upgrades`). Arrow aria-label `Runner update available`; own agent: `Runner update: you have {x}, {latest} is out.` then `Update with:` and the command; someone else's: `Runner update: this agent's runner is {x}, {latest} is out. Its owner can update it.` Commands: Windows `scoop update megoocolab-runner`; others the existing `curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh`.
- Docker: only the `megoo-e2e` compose project and the dev containers. Migrations generated and checked against `megoo_migrate` only. Never two pytest runs at once. Commit trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. GitHub unreachable, rate-limited (403) or answering garbage: the stored versions are kept, the job does not fail-loop, nothing shows before the first success (Task 2 tests).
2. A server run from source (`APP_VERSION=dev`) or already on the latest version: no pill, even for admins; a member never gets the server's versions at all (Task 3 tests).
3. Release lists with drafts, pre-releases and odd tags (`runner-v0.2.0-rc1`, `v1.0`, `docs-v9`): ignored when picking the latest (Task 2 `pick_latest` test).
4. `0.10.0` vs `0.9.0`: newer, in both the Python and the TypeScript comparison (Task 2 and Task 4 tests).
5. An offline agent, or one on a locally built runner (`0.1.0-dev+abc`): no arrow (Task 5 test).

---

### Task 1: Version files and the release tool

**Files:**
- Create: `VERSION`, `runner/VERSION`, `tools/release/versions.py`, `tools/release/test_versions.py`
- Modify: `Makefile` (runner `VERSION`)

**Interfaces:**
- Produces (`tools/release/versions.py`, standard library only, CLI `python tools/release/versions.py <command>`):
  - `parse(version: str) -> tuple[int, int, int] | None` — see Global Constraints.
  - `check(root: Path) -> list[str]` — errors: `VERSION`, pyproject and package.json versions differ, or either `VERSION` file is not a release version.
  - `guard(root: Path) -> list[str]` — errors when `backend/`, `frontend/`, `deploy/` or `VERSION` changed since the newest `v*` tag while `VERSION` still equals that tag's version; same for `runner/` (except `runner/scoop/megoocolab-runner.json`) against the newest `runner-v*` tag. No tag yet: no error.
  - `plan(root: Path) -> dict[str, str]` — runs `check` and `guard` (raising `SystemExit(1)` with the errors printed), then `{"app": "true"|"false", "app_version": ..., "runner": ..., "runner_version": ...}`; a product is `"true"` when its tag does not exist locally; a needed product whose release note file is missing is an error.
  - `update_scoop(manifest: Path, version: str, checksums: str) -> None` — sets `version`, the `64bit` / `arm64` URLs (`…/runner-v<version>/megoocolab-runner_<version>_windows_amd64.zip` / `_arm64.zip`) and their SHA-256 from the `checksums.txt` text; JSON written with 4-space indent and a trailing newline.
  - Commands: `check`, `plan` (prints `key=value` lines, for `$GITHUB_OUTPUT`), `scoop <version> <checksums-file>`.

- [ ] **Step 1: Write the failing tests** in `test_versions.py`, each in a temp git repo built by a fixture (files `VERSION`, `backend/pyproject.toml`, `frontend/package.json`, `runner/VERSION`, `runner/scoop/megoocolab-runner.json`, `docs/releases/`; one commit):
  - `parse`: `"0.1.0"`, `"v0.10.2"` → tuples; `"dev"`, `"0.1.0-dev+abc"`, `"1.0"`, `""` → `None`; `parse("0.10.0") > parse("0.9.0")`.
  - `check`: all `0.1.0` → `[]`; package.json `0.2.0` → one error naming it.
  - `guard`: no tags → `[]`; tag `v0.1.0`, change `backend/x.py`, `VERSION` still `0.1.0` → error; then `VERSION` (and the two files) `0.1.1` → `[]`; a change to `docs/` only → `[]`; tag `runner-v0.1.0`, change only `runner/scoop/megoocolab-runner.json` → `[]`, change `runner/main.go` → error.
  - `plan`: no tags, notes present → `{"app": "true", "app_version": "0.1.0", "runner": "true", "runner_version": "0.1.0"}`; tag `v0.1.0` present → `app` `"false"`; needed and `docs/releases/runner-v0.1.0.md` missing → `SystemExit`.
  - `update_scoop`: with a checksums text holding both Windows zips, the manifest's version, both URLs and both hashes are updated; other keys unchanged.
- [ ] **Step 2: Run** `uv run --project backend pytest tools/release -q -p no:cacheprovider` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `versions.py` (git through `subprocess.run(["git", "-C", root, ...])`); create `VERSION` and `runner/VERSION` with `0.1.0`.
- [ ] **Step 4: Run** the same — Expected: PASS. Then `python tools/release/versions.py check` — Expected: exit 0, no output.
- [ ] **Step 5: Makefile** — the runner version becomes `$(strip $(file < runner/VERSION))-dev+$(shell git rev-parse --short HEAD)` (still overridable with `make runner VERSION=…`); update its comment. Run `make dev-runner` and `runner/bin/megoocolab-runner version` — Expected: `0.1.0-dev+<commit>`.
- [ ] **Step 6: Commit** `feat(release): version files and the release tool`.

### Task 2: The update check (backend)

**Files:**
- Create: `backend/app/updates/__init__.py`, `backend/app/updates/versions.py`, `backend/app/updates/check.py`, migration `backend/migrations/versions/<rev>_update_check.py`
- Modify: `backend/app/core/config.py`, `backend/app/org/models.py`, `backend/app/worker.py`, `deploy/docker-compose.yml` (worker `UPDATE_CHECK: ${UPDATE_CHECK:-true}`), `deploy/.env.example`
- Test: `backend/tests/updates/__init__.py`, `backend/tests/updates/test_check.py`

**Interfaces:**
- Produces:
  - `app.updates.versions.parse(version: str | None) -> tuple[int, int, int] | None`, `is_newer(latest: str | None, current: str | None) -> bool` (False unless both parse).
  - `Settings.app_version: str = "dev"`, `Settings.update_check: bool = True`.
  - `OrgSettings` columns (all nullable): `latest_app_version: String(50)`, `latest_app_url: String(500)`, `latest_runner_version: String(50)`, `latest_runner_url: String(500)`, `updates_checked_at: DateTime(timezone=True)`.
  - `app.updates.check`: `RELEASES_URL = "https://api.github.com/repos/mmhy2003/MegooColab/releases?per_page=100"`, `CHECK_SECONDS = 6 * 3600`; `async fetch_releases() -> list[dict]` (httpx, 10 s timeout, `Accept: application/vnd.github+json`, `User-Agent: MegooColab`, raises on non-2xx); `pick_latest(releases: list[dict]) -> tuple[tuple[str, str] | None, tuple[str, str] | None]` — newest `(version, html_url)` for `v*` and for `runner-v*`, skipping drafts, pre-releases and tags that are not a release version; job `updates.check` (registered with `queue.register`, `queue.register_periodic("updates.check", CHECK_SECONDS)`).

- [ ] **Step 1: Write the failing tests** (`test_check.py`):
  - `parse`/`is_newer`: `is_newer("0.10.0", "0.9.0")`; not `is_newer("0.1.0", "0.1.0")`; not `is_newer("0.2.0", "dev")`; not `is_newer(None, "0.1.0")`; `parse("v0.2.0") == (0, 2, 0)`.
  - `pick_latest` on a list holding `v0.1.0`, `v0.2.0` (draft), `v0.1.5`, `runner-v0.2.0-rc1` (prerelease false, odd tag), `runner-v0.1.1`, `v1.0`, `docs-v9` → `(("0.1.5", url), ("0.1.1", url))`.
  - the job with `fetch_releases` monkeypatched to return that list → org row has both versions, URLs, `updates_checked_at` set.
  - then with `fetch_releases` raising `httpx.ConnectError` (and, separately, `httpx.HTTPStatusError` for a 403) → the job returns without raising and the stored values are unchanged.
  - with `Settings.update_check` false (`monkeypatch` on `get_settings()` result) → `fetch_releases` is never called.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/updates -q -p no:cacheprovider` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** settings, model columns, `versions.py`, `check.py` (failure: `log.warning` and return; store only the products found). Generate the migration against `megoo_migrate` (`alembic revision --autogenerate -m "update check"`), check `downgrade -1` / `upgrade head` there. Add `"app.updates.check"` to `HANDLER_MODULES` in `app/worker.py`, and in `_main` enqueue `updates.check` once (`dedupe_key="updates.check"`) after the handlers are imported. `.env.example`: a commented `UPDATE_CHECK=false` with one line on what it turns off.
- [ ] **Step 4: Run** the same — Expected: PASS. Then `uv run pytest tests/core/test_migrations.py -q -p no:cacheprovider` — Expected: PASS (models and migrations agree).
- [ ] **Step 5: Commit** `feat(backend): check GitHub for the latest MegooColab and runner versions`.

### Task 3: `GET /api/updates`, the image's version and agents' runner versions

**Files:**
- Create: `backend/app/updates/router.py`, `backend/app/updates/schemas.py`
- Modify: `backend/app/main.py` (router), `backend/Dockerfile` (`ARG APP_VERSION=dev` + `ENV APP_VERSION=$APP_VERSION`), `backend/app/runner/registry.py` (`RunnerConn.version: str | None`, `RunnerConn.os: str | None`), `backend/app/runner/router.py` (set both from `Hello`), `backend/app/agents/schemas.py`, `backend/app/agents/service.py` (`_base_fields`), `backend/app/tasks/schemas.py` + `backend/app/tasks/service.py` (`AssigneeAgentOut`), `backend/app/dashboard/schemas.py` + `backend/app/dashboard/agents.py` (`AgentItem`), `frontend/src/lib/api-types.ts` (regenerate with `npm run gen:api`)
- Test: `backend/tests/updates/test_router.py`, plus one assertion each in the existing agents / tasks / dashboard tests that already connect a fake runner

**Interfaces:**
- Consumes: Task 2 `is_newer`, `OrgSettings.latest_*`, `Settings.app_version`.
- Produces:
  - `UpdatesOut { app: AppUpdate | None; runner: RunnerRelease | None }`, `AppUpdate { current: str; latest: str; url: str }`, `RunnerRelease { latest: str; url: str }`. `app` is set only when the viewer is an admin and `is_newer(latest_app_version, settings.app_version)`; `runner` whenever a runner version is stored.
  - `RunnerInfo { version: str; os: str }` (in `app/agents/schemas.py`); `runner_info(owner_id: uuid.UUID) -> RunnerInfo | None` in `app/agents/service.py` (None when the owner has no live connection or the hello had no version).
  - New field `runner: RunnerInfo | None = None` on `AgentOut`, `AssigneeAgentOut` and the dashboard `AgentItem`; `AgentItem` also gets `owner_id: uuid.UUID`.

- [ ] **Step 1: Write the failing tests** (`test_router.py`): org row with `latest_app_version="0.2.0"`, `latest_runner_version="0.1.1"` and URLs; `get_settings().app_version` monkeypatched:
  - admin, app `0.1.0` → `app == {"current": "0.1.0", "latest": "0.2.0", "url": …}`, `runner == {"latest": "0.1.1", "url": …}`.
  - member, app `0.1.0` → `app is None`, `runner` set.
  - admin, app `dev` → `app is None`; admin, app `0.2.0` → `app is None`.
  - nothing stored → both `None`.
  - an agent whose owner's fake runner said hello with `runner_version="0.1.0", os="windows"` → `GET /api/agents/mine` item has `runner == {"version": "0.1.0", "os": "windows"}`; owner offline → `runner is None`. Same field on the task's `assignee_agent` and the dashboard agents item (in the existing test files that already drive a runner hello).
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/updates -q -p no:cacheprovider` — Expected: FAIL.
- [ ] **Step 3: Implement**; regenerate `frontend/src/lib/api-types.ts`.
- [ ] **Step 4: Run** `cd backend && uv run pytest -q -p no:cacheprovider` (whole suite) — Expected: PASS. `cd frontend && npx tsc --noEmit` — Expected: no errors.
- [ ] **Step 5: Commit** `feat(backend): latest versions endpoint and each agent's runner version`.

### Task 4: The "Update" pill

**Files:**
- Create: `frontend/src/lib/versions.ts`, `frontend/src/lib/updates.ts`, `frontend/src/components/shell/UpdatePill.tsx`
- Modify: `frontend/src/lib/queries.ts` (`updates: () => ["updates"] as const`), `frontend/src/lib/types.ts` (export `Updates`, `RunnerInfo`), `frontend/src/components/shell/Header.tsx` (pill just before `<NotificationBell />`), `frontend/src/components/agents/RunnerSetup.tsx` (export the two install commands as `RUNNER_INSTALL`)
- Test: `frontend/src/lib/__tests__/versions.test.ts`, `frontend/src/components/shell/__tests__/UpdatePill.test.tsx`

**Interfaces:**
- Consumes: Task 3 `UpdatesOut`.
- Produces: `parseVersion(v?: string | null): [number, number, number] | null`, `isNewer(latest?: string | null, current?: string | null): boolean` (same rules as Task 2); `useUpdates()` — TanStack query on `qk.updates()` → `GET /api/updates`, `staleTime` and `refetchInterval` 1 hour; `RUNNER_INSTALL: { windows: string; unix: string }`.

- [ ] **Step 1: Write the failing tests**
  - `versions.test.ts`: same cases as Task 2's `parse`/`is_newer`, including `isNewer("0.10.0", "0.9.0")`.
  - `UpdatePill.test.tsx` (fetch mocked): `app` set → a button named `Update available: MegooColab 0.2.0` with text `Update`; clicking shows `MegooColab 0.2.0`, `You're on 0.1.0.`, a `What's new` link to the release URL and a `How to update` link to the install guide URL; `app: null` → nothing rendered.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/lib/__tests__/versions.test.ts src/components/shell/__tests__/UpdatePill.test.tsx` — Expected: FAIL.
- [ ] **Step 3: Implement** — the pill uses the existing shadcn `Popover` (as `NotificationBell` does); style: small rounded pill, cyan background, `--on-accent` text; links open in a new tab.
- [ ] **Step 4: Run** the same — Expected: PASS.
- [ ] **Step 5: Commit** `feat(frontend): Update pill in the header when a newer MegooColab is out`.

### Task 5: The runner arrow

**Files:**
- Create: `frontend/src/components/agents/RunnerUpdateArrow.tsx`
- Modify: next to each `AgentStatusDot` — `app/(app)/settings/agents/page.tsx`, `app/(app)/admin/agents/page.tsx`, `app/(app)/teams/[id]/page.tsx`, `components/board/TaskCard.tsx`, `components/workflow/WorkflowPanel.tsx` — and the dashboard `components/dashboard/AgentsCard.tsx`
- Test: `frontend/src/components/agents/__tests__/RunnerUpdateArrow.test.tsx`

**Interfaces:**
- Consumes: Task 3 `RunnerInfo` / `runner` fields; Task 4 `useUpdates`, `isNewer`, `RUNNER_INSTALL`.
- Produces: `RunnerUpdateArrow({ runner, mine }: { runner?: RunnerInfo | null; mine: boolean })` — renders only when `isNewer(updates.runner?.latest, runner?.version)`; an amber `↑` button (aria-label `Runner update available`) whose details open on hover/focus (shadcn `Tooltip`) and on click/tap (shadcn `Popover`), text per Global Constraints; the command is the Windows one when `runner.os === "windows"`, else the unix one. `mine` = the agent's owner is the signed-in user (`a.owner.id`, `assignee_agent.owner_id`, `AgentItem.owner_id` vs `useMe()`).

- [ ] **Step 1: Write the failing tests** (`useUpdates` data mocked with `runner.latest = "0.2.0"`):
  - `runner {version: "0.1.0", os: "windows"}`, `mine` → button `Runner update available`; clicking shows `Runner update: you have 0.1.0, 0.2.0 is out.` and `scoop update megoocolab-runner`.
  - `os: "linux"` → the `curl … install.sh | sh` command.
  - `mine` false → `Runner update: this agent's runner is 0.1.0, 0.2.0 is out. Its owner can update it.` and no command.
  - `runner` null (offline), `version: "0.1.0-dev+abc"`, `version: "0.2.0"` (current), and `updates.runner` null → nothing rendered.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/components/agents/__tests__/RunnerUpdateArrow.test.tsx` — Expected: FAIL.
- [ ] **Step 3: Implement** the component and place it right after each `AgentStatusDot` (and after the dot in `AgentsCard`).
- [ ] **Step 4: Run** `cd frontend && npx vitest run && npm run lint && npx tsc --noEmit` — Expected: all pass.
- [ ] **Step 5: Commit** `feat(frontend): an arrow on agents whose runner is out of date`.

### Task 6: Compose from images, local builds, install docs

**Files:**
- Create: `deploy/docker-compose.build.yml`
- Modify: `deploy/docker-compose.yml` (backend, worker, frontend: `image: ghcr.io/mmhy2003/megoocolab-<backend|frontend>:${MEGOO_VERSION:-latest}`, no `build:`), `deploy/.env.example` (commented `MEGOO_VERSION=0.1.0` with "pin a version; default the latest"), `Makefile` (`COMPOSE` uses both files), `README.md` (Install section; every `megoo-e2e` command gains `-f deploy/docker-compose.build.yml`), `docs/install.md` (§2 Get the code, §4 Start: `docker compose pull` then `up -d`, §12 Upgrades: `git pull`, `docker compose pull`, `docker compose up -d`, pinning with `MEGOO_VERSION`)

**Interfaces:**
- Produces: `docker-compose.build.yml` with only `build:` for `backend` (`../backend`), `worker` (`../backend`), `frontend` (`../frontend`); the backend's build passes `APP_VERSION` from the environment (`args: { APP_VERSION: "${APP_VERSION:-dev}" }`).

- [ ] **Step 1: Verify** `docker compose -f deploy/docker-compose.yml --env-file .superpowers/e2e.env config` shows the three `ghcr.io/...:latest` images and no build; with `-f deploy/docker-compose.build.yml` added it shows the builds. Expected: both commands succeed.
- [ ] **Step 2: README install section** — clone, `cd MegooColab/deploy`, `cp .env.example .env` and fill in the required values, `docker compose pull`, `docker compose up -d`; updating: `git pull`, `docker compose pull`, `docker compose up -d`; pointer to `docs/install.md`. `docs/install.md` sections changed to match.
- [ ] **Step 3: Commit** `feat(deploy): servers run the published images; local builds through docker-compose.build.yml`.

### Task 7: CI gate and the release workflow

**Files:**
- Create: `.github/workflows/release.yml`, `docs/releasing.md`
- Modify: `.github/workflows/ci.yml` (add `workflow_call:`; new job `release-tools`: setup-python 3.12, `pip install pytest`, `pytest tools/release -q`, `python tools/release/versions.py check`)
- Delete: `.github/workflows/runner-release.yml`

**Interfaces:**
- Consumes: Task 1 CLI (`plan`, `scoop`), Task 3 Dockerfile `APP_VERSION`, Task 6 compose files.
- Produces: `release.yml` — `on: push: branches: [main]`; `permissions: contents: write, packages: write`; `concurrency: release`. Jobs:
  - `plan`: checkout `fetch-depth: 0`; `python tools/release/versions.py plan >> "$GITHUB_OUTPUT"`; outputs `app`, `app_version`, `runner`, `runner_version`.
  - `tests`: `needs: plan`, `if: app == 'true' || runner == 'true'`, `uses: ./.github/workflows/ci.yml`.
  - `app` (`if: app == 'true'`): QEMU + Buildx + GHCR login; build both images for `linux/amd64` with `load: true` tagged `:smoke` (`APP_VERSION` build arg); `MEGOO_VERSION=smoke docker compose -f deploy/docker-compose.yml --env-file <throwaway .env written in the job> up -d --wait --pull never`, then `down -v`; build and push both images for `linux/amd64,linux/arm64`, tags `<version>` and `latest`, `cache-from/to: type=gha`; `gh release create "v$V" --target "$GITHUB_SHA" --title "MegooColab $V" --notes-file "docs/releases/v$V.md"`.
  - `runner` (`if: runner == 'true'`): setup-go; `git tag "v$V"` locally (GoReleaser needs a tag; it is never pushed); GoReleaser as in the old workflow (`GORELEASER_CURRENT_TAG=v$V`, `--skip=publish,validate`); `gh release create "runner-v$V" --target "$GITHUB_SHA" --title "Runner $V" --notes-file "docs/releases/runner-v$V.md"` with the archives and `checksums.txt`; `python tools/release/versions.py scoop "$V" runner/dist/checksums.txt`; commit `chore(runner): Scoop manifest for runner $V` as `github-actions[bot]` and push to `main`, then apply the same file on `develop` and push.
- `docs/releasing.md`: the routine from the spec (list changes per product since its tag, propose bumps, write notes in `docs/releases/`, merge `develop` into `main` with `--no-ff`, one commit with versions and notes, run the browser tests on `develop` beforehand, push `main`, merge `main` back into `develop`), what the workflow does, and the one-time "make both GHCR packages public" step.

- [ ] **Step 1: Verify** `go run github.com/rhysd/actionlint/cmd/actionlint@latest` at the repository root — Expected: no findings for `ci.yml` and `release.yml`.
- [ ] **Step 2: Verify** `python tools/release/versions.py plan` on this branch — Expected: exit 1 naming the missing `docs/releases/v0.1.0.md` and `docs/releases/runner-v0.1.0.md` (no tags yet, notes come with the first release).
- [ ] **Step 3: Commit** `feat(release): release workflow on pushes to main`.

### Task 8: Whole-stack check

- [ ] **Step 1:** Rebuild and start the e2e stack with both compose files: `docker compose -p megoo-e2e -f deploy/docker-compose.yml -f deploy/docker-compose.build.yml --env-file .superpowers/e2e.env up -d --build --wait`. Expected: healthy.
- [ ] **Step 2:** `cd frontend && npx playwright test` — Expected: all pass. Then `down -v`.
- [ ] **Step 3:** Run every suite once more on the branch tip: backend pytest, frontend vitest + lint + tsc, `go test ./...` in `runner`, `pytest tools/release`. Expected: all pass.
