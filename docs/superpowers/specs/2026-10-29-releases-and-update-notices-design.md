# Releases, versions and update notices — design

Date: 2026-10-29. Status: draft for approval.

## Why

MegooColab has so far been built and run straight from `main`: every server builds its own Docker images from a
clone, and the runner has a tag-triggered release workflow that has never run (the Scoop manifest still says
0.0.0). The owner wants a real release process: development on a `develop` branch, a release whenever `main` is
updated, published Docker images and runner binaries with proper version numbers and release notes, and a way for
people using MegooColab to see that a newer version exists.

## Goals

1. **Branches.** A `develop` branch holds day-to-day work; feature branches merge into it. `main` changes only on a
   release, and stays GitHub's default branch, so a plain `git clone` gets the latest release.
2. **Two products, versioned separately.** *MegooColab* (the server: backend, worker and frontend, one number) and
   *the runner*. Either can be released without the other. Both start at **0.1.0**.
3. **Version numbers** are `major.minor.build`:
   - build (0.1.0 → 0.1.1): fixes and small improvements only;
   - minor (0.1.1 → 0.2.0): new features;
   - major: a change an admin must act on (a new required `.env` setting, say). Going to 1.0.0 is the owner's call.
4. **A version changes only when a release goes to `main`.** Never on `develop` or a feature branch.
5. **Every push to `main` releases whatever has a new version**, through GitHub Actions:
   - MegooColab: Docker images to the GitHub registry and a GitHub release `vX.Y.Z`;
   - runner: binaries for Windows, macOS and Linux (amd64 and arm64) and a GitHub release `runner-vX.Y.Z`.
   A push to `main` with no new version releases nothing.
6. **Every release has a written release note**: all its features, fixes and improvements in plain words for the
   people who install it, shown on the GitHub release page. Not an auto-generated commit list.
7. **Servers install and update from published images**: clone, `cd deploy`, write `.env`, `docker compose pull`,
   `docker compose up -d`. Updating is `git pull`, `docker compose pull`, `docker compose up -d`; migrations run by
   themselves (the backend already migrates on start and the worker waits for it).
8. **Update notices in the app:**
   - a newer MegooColab: a quiet **"Update" pill** in the header, next to the bell (mockup option C);
   - a newer runner: an **amber ↑** next to an agent's status dot, details on hover (mockup option A).

## Non-goals

- Updating anything automatically (servers or runners). The app only tells people.
- Pre-releases, release candidates, nightly images, or images per `develop` commit.
- Changing `docker-compose.dev.yml` (`make dev` keeps running only the database, search and Valkey in Docker).
- A changelog page inside the app (the notice links to the GitHub release).

## Anti-goals (a failure even if it works)

- A version bump on `develop` or in a feature branch.
- A release whose page has no real release note.
- A release that publishes something the tests have not passed on.
- A `git clone` that lands on unreleased work.
- The install commands shown in the app (`curl … install.sh | sh`, `scoop install …`) failing after a release.
- An update notice that nags: popping up by itself, or shown to people who cannot act on it.

## Decided by the owner

- `develop` for development; release = updating `main`.
- Separate versions for MegooColab and the runner, both starting at 0.1.0.
- `major.minor.build`, bumped only when releasing to `main`.
- A good release note on every release.
- Servers use registry images, `latest` by default; local builds stay possible for development and tests.
- Install guide in the README: clone, `cd deploy`, `.env`, pull, up.
- Notices: header "Update" pill (C); runner ↑ with hover (A).
- The runner binary stays `megoocolab-runner` (`.exe` on Windows), so the documented install commands keep working.

## How it works

### Branches and the release routine

- `develop` is created from `main` as it is when this work starts, and pushed. From then on, finished work merges
  into `develop` (the "merge locally" step of finishing a branch now targets `develop`). CI keeps running on every
  push, `develop` included.
- A release happens only when the owner says so. The routine (Claude's, documented in `docs/releasing.md`):
  1. List what changed per product since its last release tag (`v*` for MegooColab, `runner-v*` for the runner;
     before the first release, everything).
     Paths that count for MegooColab: `backend/`, `frontend/`, `deploy/`. For the runner: `runner/`.
  2. Propose the bump for each product that changed (build / minor / major, by the rules above); the owner
     confirms or changes the size. *Claude's call:* every product with changes since its last release is bumped
     in that release; "one without the other" means the other had no changes. Merging `develop` brings all of
     its changes to `main`, so an unbumped product would put unreleased code (or a compose file written for
     images not yet published) on `main`. The release workflow enforces it: it fails, before publishing anything,
     when `backend/`, `frontend/` or `deploy/` changed since the last `v*` tag without a new `VERSION`, or
     `runner/` changed since the last `runner-v*` tag without a new `runner/VERSION` (the Scoop manifest commit
     excepted).
  3. On `main`: merge `develop` (`--no-ff`), then one commit that sets the new version(s) and adds the release
     note(s). Push `main`. Then merge `main` back into `develop` and push it, so `develop` carries the version.
- The version lives in one place per product (see below); the release commit is the only commit that changes it.

### Where versions live

- MegooColab: a `VERSION` file at the repository root holding `0.1.0`. `backend/pyproject.toml` and
  `frontend/package.json` carry the same number; CI fails if any of the three differ.
- Runner: `runner/VERSION` holding `0.1.0`. The Makefile's local runner build reads it (instead of `git describe`)
  and adds a suffix, `0.1.0-dev+<commit>` (*Claude's call*), so a local build is never mistaken for a release:
  any version with a `-` suffix counts as a local build and shows no update arrow.
- The backend knows its own version at run time: the image build passes it in (a build argument baked into the
  image's environment). Run from source (`make dev`) it reports `dev`, and no update pill shows.

### Release notes

- One Markdown file per release: `docs/releases/v0.1.0.md` and `docs/releases/runner-v0.1.0.md`.
- Written by Claude at release time from the changes since the last release: grouped under **New**, **Improved**,
  **Fixed** (empty groups left out), each line a plain sentence for the person installing it. For MegooColab, an
  **Upgrading** section when the release needs anything beyond pull and up (a `git pull` for a changed compose
  file, a new `.env` setting).
- The release workflow publishes the file as the release body. A new version without its note file fails the
  workflow before anything is published.

### The release workflow (`.github/workflows/release.yml`, on push to `main`)

1. **Run the tests**: the existing CI jobs, reused (ci.yml made callable), plus the bump guard above. Nothing
   publishes unless they pass.
   *Claude's call:* the browser (Playwright) tests are not part of the release gate. They need a fresh stack, Go
   and the fake agent, and would add a long job to every release. Instead, before pushing the images, the
   workflow starts the stack from the freshly built images (`docker compose` with a throwaway `.env`) and waits
   until the backend is healthy, so an image that cannot start is never published. The browser tests stay a step
   in Claude's release routine, run locally on `develop` before merging to `main`.
2. **MegooColab**, if no release `v<VERSION>` exists yet:
   - build and push, for linux/amd64 and linux/arm64:
     - `ghcr.io/mmhy2003/megoocolab-backend` (the backend and the worker share it);
     - `ghcr.io/mmhy2003/megoocolab-frontend`;
     each tagged `<VERSION>` and `latest`;
   - create the GitHub release `v<VERSION>` (title "MegooColab <VERSION>") with the note as its body.
3. **Runner**, if no release `runner-v<VERSION>` exists yet:
   - GoReleaser as today (same archive names: `megoocolab-runner_<version>_<os>_<arch>`, `.zip` on Windows,
     `checksums.txt`);
   - create the GitHub release `runner-v<VERSION>` (title "Runner <VERSION>") with the note as its body;
   - update `runner/scoop/megoocolab-runner.json` with the new version, URLs and SHA-256 hashes, and commit it to
     `main` and to `develop`. (Pushes made with the workflow's own token start no new workflow run.)
- The old tag-triggered `runner-release.yml` is removed.
- One-time manual step for the owner: GitHub makes new registry packages private; after the first release, set
  both packages to public, or servers cannot pull without signing in. `docs/releasing.md` says so.

### Compose files

- `deploy/docker-compose.yml` (servers): backend, worker and frontend use
  `ghcr.io/mmhy2003/megoocolab-<name>:${MEGOO_VERSION:-latest}`, no `build:`. `MEGOO_VERSION` is documented in
  `.env.example` (pin a version; default the latest).
- `deploy/docker-compose.build.yml` (new): adds the `build:` lines back for the same three services. `make build`,
  `make up` and the end-to-end test stack (`megoo-e2e`, README instructions) use both files and build from the local
  code.
- `deploy/docker-compose.dev.yml`: unchanged.

### Docs

- README "Install (self-hosted)": clone, `cd MegooColab/deploy`, `cp .env.example .env` and fill in the required
  values, `docker compose pull`, `docker compose up -d`. Updating: `git pull`, `docker compose pull`,
  `docker compose up -d`. Details stay in `docs/install.md` (its "Get the code", "Start" and "Upgrades" sections
  change to match).
- `docs/releasing.md` (new): the release routine above, for whoever releases.

### Knowing the latest versions

- The worker asks GitHub's API for the repository's releases (`GET /repos/mmhy2003/MegooColab/releases`,
  unauthenticated) every 6 hours and on start, and stores the newest `v*` and newest `runner-v*` version with their
  release page URLs and the time checked (org settings).
- No network, an error or a rate limit: keep what was stored, try again next time. Nothing shows until a check has
  succeeded once.
- `UPDATE_CHECK=false` in `.env` turns the check off (servers with no internet, or that should not call GitHub);
  documented in `.env.example`.
- Versions compare numerically per part (0.10.0 is newer than 0.9.0).

### The "Update" pill (MegooColab)

- Shown in the header, just before the notification bell, **to admins only**, when the server's version is older
  than the latest MegooColab release. Not shown when the server runs from source (`dev`).
- Clicking it opens a small popover: "MegooColab <latest>" / "You're on <current>.", a **What's new** link (the
  release page) and a **How to update** link (the Upgrades section of `docs/install.md` on GitHub).
- It never opens by itself and has no dismiss: it stays until the server is updated. Keyboard reachable, with an
  accessible name such as "Update available: MegooColab <latest>".

### The runner ↑

- The runner already sends its version when it connects (`hello.runner_version`); the server keeps it on the live
  connection and includes it with each agent of that runner's owner (`runner_version`, absent when offline).
- Where an agent's status dot appears (My agents, the dashboard's Agents card, Admin → Agents, the team page, the
  task card, the workflow panel), an amber ↑ appears next to it when that agent's runner is older than the latest
  runner release. Offline agents show no arrow (their version is unknown).
- Hover, focus or tap shows: "Runner update: you have <x>, <latest> is out." and how to update: on Windows
  `scoop update megoocolab-runner`; on macOS or Linux, the install command again (`curl … install.sh | sh`).
  On someone else's agent the text says the owner can update it.
- A runner built locally (`dev` or `0.0.0-…` version) shows no arrow.

## Delivery and the first release

*Claude's call:* this work is built and merged into `develop` only. Nothing reaches `main` until the owner says
"release". That first release is v0.1.0 and runner-v0.1.0 (no tags exist yet), with release notes covering
everything so far, written then. Right after it publishes, the owner sets the two registry packages to public;
until then a fresh install cannot pull the images. Existing servers are unaffected until their admin updates.

## Left to the builder

- The exact API shape for the latest versions (a small endpoint, or fields on an existing one) and where the
  frontend reads the server's own version.
- How ci.yml is made reusable, and how the release workflow detects "no release for this version yet".
- Buildx/QEMU setup for the arm64 images and caching.
- Tests: the version comparison, the update check (stored / kept on failure / off), who sees the pill, the arrow's
  conditions, and the compose files (`docker compose config` on both combinations).

## Open guesses (Claude's, not yet confirmed)

- Only admins see the Update pill; everyone sees the runner arrow.
- The check runs every 6 hours, and can be turned off with `UPDATE_CHECK=false`.
- Images for amd64 and arm64.
