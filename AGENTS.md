# Working in MegooColab

Rules for coding agents working in this repository. The owner gives short instructions ("push", "release", "1");
this file says what each one means here. [README.md](README.md) has the development set-up and the test commands,
and [docs/releasing.md](docs/releasing.md) is the full reference for releases.

## Branches

- `develop` is where work lands. `main` changes only on a release, and stays GitHub's default branch.
- Start every piece of work on its own branch off `develop`: `feat/…`, `fix/…` or `docs/…`. Never commit straight
  to `develop` or `main`.
- When the work is done and its checks pass, offer exactly these choices, then wait for the answer:

  ```
  1. Merge back to develop locally
  2. Push and create a Pull Request
  3. Keep the branch as-is (I'll handle it later)
  ```

  "1" means `git merge --no-ff <branch>` into `develop`, run the checks again on the result, then delete the branch.
  It does not push.
- **Push only when the owner says "push"**, and **release only when the owner says "release"**. Neither is implied
  by a merge, or by an earlier "push" or "release" for other work.

## Before building

- A change to what people see (a page, a dialog, a layout) gets a mockup first. Build it only after the owner
  approves the mockup.
- Write the test first and watch it fail, then make it pass. A bug fix starts with a test that reproduces it.

## Checks

- **Frontend** (`frontend/`): `npx tsc --noEmit`, `npx eslint <changed files>` and `npm test` (Vitest). Don't run
  Prettier or reformat files you didn't otherwise change. After an API change, `npm run gen:api`.
- **Backend** (`backend/`): `uv run pytest`. Never start a second pytest run while one is going: they share the test
  databases.
- **Migrations**: generate and try them only against the scratch database `megoo_migrate`, never the dev database
  `megoo`:

  ```bash
  docker exec megoocolab-dev-db-1 psql -U megoo -d postgres -c "CREATE DATABASE megoo_migrate"   # once
  DEV_DATABASE_URL=postgresql+asyncpg://megoo:megoo@localhost:5433/megoo_migrate bash backend/scripts/makemigration.sh "<message>"
  ```

  Give every new foreign key and unique constraint an explicit name, and check that the migration goes down and up
  again on `megoo_migrate`: in `backend/`, with `SECRET_KEY=dev` and
  `DATABASE_URL=postgresql+asyncpg://megoo:megoo@localhost:5433/megoo_migrate`, run
  `uv run alembic downgrade -1 && uv run alembic upgrade head`.
- **Runner** (`runner/`): `go test ./...`.
- **Browser tests** (Playwright, `frontend/e2e/`): run them on a freshly built stack before merging a change to the
  app. The dev Caddy holds port 8080, so stop it first and start it again afterwards:

  ```bash
  C="docker compose -p megoo-e2e -f deploy/docker-compose.yml -f deploy/docker-compose.build.yml --env-file .superpowers/e2e.env"
  docker stop megoocolab-dev-caddy-1
  $C down -v; $C up -d --build --wait
  (cd frontend && npx playwright test --reporter=line)
  $C down -v
  docker start megoocolab-dev-caddy-1
  ```

  A spec written only to take screenshots is named `zz-*.spec.ts` and deleted before committing.

## Safety

- Docker: use only the `megoo-e2e` project and the dev containers (`megoocolab-dev-*`). Never stop, remove or
  change `cloudflared` or any other `megoocolab-*` container: those run the owner's real instance.
- Never read files that hold credentials or secrets (`.env` files, tokens, keys). For `.superpowers/e2e.env`, show
  its key names only, never the values.
- You have no access to the production server. Don't try to reach it.

## Commits

- Subject: `type(area): what changed`, as a plain sentence, for example
  `fix(chats): the project picker lists projects that load after it opens`. Types: `feat`, `fix`, `docs`, `test`,
  `refactor`, `chore`.
- Body: why the change was needed and what it does, in plain sentences.
- Merges keep git's message: `Merge branch '<branch>' into develop`.

## Releasing

Two products are released, each with its own version: **MegooColab** (backend, worker and frontend; tag
`vX.Y.Z`) and **the runner** (tag `runner-vX.Y.Z`). The version never changes on `develop` or on a work branch:
only in the release commit.

When the owner says "release":

1. **Decide what's released.** On `develop`, list what changed since each product's last tag:
   `git log vX.Y.Z..develop -- backend frontend deploy` and `git log runner-vX.Y.Z..develop -- runner`. Every
   product with changes is released; documentation alone needs no release.
2. **Pick the bump yourself**, and say which one you picked:
   - fixes and small improvements only: the last number (0.14.5 → 0.14.6);
   - any new feature: the middle number (0.14.6 → 0.15.0);
   - the first number only when the owner asks, or for a change an admin must act on (ask first).
3. **Merge:** `git checkout main && git pull && git merge --no-ff develop -m "Merge branch 'develop'"`.
4. **Set the new version** in every file that holds it:
   - MegooColab: `VERSION`, `backend/pyproject.toml` (`version = …`), the `megoocolab-backend` entry in
     `backend/uv.lock`, `frontend/package.json`, and both top `"version"` lines of `frontend/package-lock.json`
     (lines 3 and 9);
   - the runner: `runner/VERSION`.
5. **Write the release note**: `docs/releases/vX.Y.Z.md` (and `docs/releases/runner-vX.Y.Z.md`). Every release
   gets a full note, written for the person installing it, not as commit messages:
   - one opening sentence saying what the release does;
   - `## New`, `## Improved`, `## Fixed`, leaving out any that would be empty. Each item starts with a bold
     sentence and goes on to explain what the person will notice;
   - `## Upgrading` last: what to do beyond pull and restart (a database change, a new `.env` setting, a changed
     compose file), or that nothing else is needed, and whether the runner needs updating.
6. **Check:** `git add` the changed files, then `python tools/release/versions.py check` and
   `python tools/release/versions.py plan`. Both must pass, and `plan` must list exactly what you mean to release.
   `check` doesn't look at the two lock files, so check those yourself:
   `git diff --cached backend/uv.lock frontend/package-lock.json` shows the new version in three places.
7. **Commit and push:** `git commit -m "release: MegooColab X.Y.Z"` (or `"release: MegooColab X.Y.Z, runner X.Y.Z"`),
   then `git push origin main`.
8. **Bring develop up to date:** `git checkout develop && git merge main && git push origin develop`.
9. **Watch the Release workflow** (`gh run list --workflow Release`, then `gh run watch <id>`) until every job is
   green and the release shows as Latest (`gh release list --limit 1`).
   - If the only failure is the runner test `TestSteerAfterTurnEndsReportsNotRunningAndCancelsStrayTurn` (it is
     known to be flaky), re-run the failed jobs once: `gh run rerun <id> --failed`. Any other failure: stop and
     report it.
   - A runner release makes the workflow commit the Scoop manifest to `main` and `develop`: `git pull` both
     afterwards.
10. **Report** the version, what it contains, that the workflow is green, and what upgrading needs.
