# Releasing MegooColab

Two products are released, each with its own version:

| Product | Version file | Tag | What gets published |
| --- | --- | --- | --- |
| MegooColab (backend, worker, frontend) | `VERSION` (and the same number in `backend/pyproject.toml` and `frontend/package.json`) | `vX.Y.Z` | Docker images `ghcr.io/mmhy2003/megoocolab-backend` and `-frontend`, tagged `X.Y.Z` and `latest` (amd64 and arm64) |
| The runner | `runner/VERSION` | `runner-vX.Y.Z` | `megoocolab-runner` for Windows, macOS and Linux (amd64 and arm64), and the Scoop manifest |

## Branches

- Work happens on `develop`; feature branches merge into it. The version never changes there.
- `main` changes only on a release, and stays GitHub's default branch, so a plain `git clone` gets the latest
  release.

## Version numbers

`major.minor.build`:

- **build** (0.1.0 → 0.1.1): fixes and small improvements only;
- **minor** (0.1.1 → 0.2.0): new features;
- **major**: a change an admin must act on, such as a new required `.env` setting. Going to 1.0.0 is the owner's
  decision.

Every product that changed since its last release is bumped in that release: merging `develop` brings all of its
changes to `main`. The release workflow refuses to publish otherwise. Changes that count:

- MegooColab: `backend/`, `frontend/`, `deploy/`, `VERSION`;
- the runner: `runner/`, except the Scoop manifest.

Documentation-only changes need no release.

## The routine

1. On `develop`, list what changed per product since its last tag: `git log v0.1.0..develop -- backend frontend
   deploy` and `git log runner-v0.1.0..develop -- runner` (before the first release, everything).
2. Propose the bump for each product that changed; the owner confirms or changes it.
3. Write each release note: `docs/releases/vX.Y.Z.md`, `docs/releases/runner-vX.Y.Z.md`.
   - Group the changes under **New**, **Improved** and **Fixed**, leaving out any empty group. Write each line as a
     plain sentence for the person installing it, not a commit message.
   - For MegooColab, add an **Upgrading** section when the release needs more than pull and up: a `git pull` for
     a changed compose file, or a new `.env` setting.
   - The workflow publishes the note as the release page and refuses a release without one.
4. Run the browser tests on `develop` against a freshly built stack (README, "End-to-end test").
5. Release:

   ```bash
   git checkout main && git pull
   git merge --no-ff develop
   # set the new version(s): VERSION + backend/pyproject.toml + frontend/package.json, and/or runner/VERSION;
   # add the release note(s)
   python tools/release/versions.py plan      # must list what is about to be released, without errors
   git commit -am "release: MegooColab X.Y.Z, runner X.Y.Z"
   git push origin main
   git checkout develop && git merge main && git push origin develop
   ```

6. Watch the **Release** workflow on GitHub. When it is green, the releases are on the
   [releases page](https://github.com/mmhy2003/MegooColab/releases).

## What the workflow does (`.github/workflows/release.yml`)

On every push to `main`:

1. `tools/release/versions.py plan` checks the version files, the bump rule and the release notes, and decides
   which products need a release: those whose version has no tag yet.
2. If something needs releasing, the whole CI suite runs (`ci.yml`). Nothing is published unless it passes.
3. **MegooColab**:
   - builds both images and starts the stack from them;
   - once the backend is healthy, publishes the images for amd64 and arm64;
   - creates the `vX.Y.Z` release with its note.
4. **Runner**:
   - builds the binaries with GoReleaser;
   - creates the `runner-vX.Y.Z` release with the archives and `checksums.txt`;
   - commits the updated Scoop manifest to `main` and `develop`.

## Once, after the very first release

GitHub makes new registry packages private. Open your GitHub profile → **Packages**, and for both
`megoocolab-backend` and `megoocolab-frontend`: **Package settings** → **Change visibility** → **Public**.
Until then, servers cannot pull the images without signing in.
