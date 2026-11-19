# MC-68: Show the current version in the sidebar footer

## Goal

Everyone who is signed in sees which MegooColab version the server runs, as a quiet "v0.23.1" at the bottom of the sidebar. A click opens that release's notes on GitHub.

The mockup approved with this design is version 3, "Version in the sidebar footer: final (all states)".

## Decisions

| Question | Decision | Why, and what was rejected |
|---|---|---|
| Where | **Sidebar footer**, on the Collapse row, at the right | Chosen by the owner from four mockups. Rejected: a badge under the logo (the name already fills the line, so the badge makes the brand block taller), a line in the user menu (hidden until opened), an "About" card in Admin → Settings (admins only, two clicks away). |
| Who sees it | **Everyone signed in** | Chosen by the owner: it helps in bug reports. Rejected: admins only. People who are not signed in still see nothing. |
| Click | **Link to this release's notes**, in a new tab | Chosen by the owner. Rejected: plain text only, and a popover (overlaps with the header's Update pill). |
| Build from source | Plain text `dev`, no link | Follows from the chosen click behaviour: a build from source has no release page. |
| How the version reaches the page | One new field on the existing `GET /api/updates` | The page already loads this for every signed-in person and refreshes it every 15 minutes, so there is no extra request, and the footer follows a server upgrade without a reload. Rejected: a new `GET /api/version` endpoint (one more request and one more cache entry for a single string). |
| Update notices | Unchanged | The header's Update pill still tells admins about a newer release. The latest release (`app.latest`, `app.url`) stays admins-only; members get only the running version. |

## Architecture

**Backend** (`backend/app/updates/`)

- `schemas.py`: `UpdatesOut` gets `app_version: str`, the version this server runs.
- `router.py`: `get_updates` sets `app_version=get_settings().app_version` on both of its returns (also when the organization is not set up yet). The admin-only rule for `app` does not change. The docstring says the running version is for everyone.

**Frontend**

- `frontend/src/lib/api-types.ts`: regenerated with `npm run gen:api`.
- `frontend/src/lib/versions.ts`, two pure helpers next to `parseVersion`:
  - `versionLabel(v)`: `"0.23.1"` or `"v0.23.1"` gives `"v0.23.1"`; anything else (`"dev"`, `"0.24.0-dev+abc"`) is returned trimmed, as it is.
  - `releaseUrl(v)`: `https://github.com/mmhy2003/MegooColab/releases/tag/v0.23.1` for a release version, `null` for anything else.
- New `frontend/src/components/shell/AppVersion.tsx`: reads `useUpdates().data?.app_version` (the query the Update pill already uses).
  - No version yet (loading, or the request failed): renders nothing.
  - A release: an `<a target="_blank" rel="noreferrer">` to `releaseUrl`, text `versionLabel`, wrapped in the existing `Hint` with "MegooColab 0.23.1: release notes". Its accessible name is "MegooColab 0.23.1, release notes (opens in a new tab)".
  - Anything else: a plain `<span>` with the text, and a visually hidden "MegooColab " before it for screen readers.
  - Look: `text-xs text-muted-foreground tabular-nums whitespace-nowrap no-underline`; the link turns `text-cyan-ink` and underlined on hover and keyboard focus. It takes a `className` so the caller can hide it.
- `frontend/src/components/shell/DesktopSidebar.tsx`: the Collapse button and `<AppVersion>` share one row (`m-2 flex items-center`). The button keeps its natural width and no longer stretches across the row; the version is pushed to the right (`ml-auto pr-3`). On the collapsed rail the version gets `LABEL_HIDDEN`, like every label: invisible while the rail is closed, shown as it slides open. Tabbing onto the link opens the rail (the existing `has-[:focus-visible]` rule), so a focused link is never invisible.
- `frontend/src/app/(app)/layout.tsx`: the phone menu's `<aside>` becomes a column: `<Sidebar>` fills it (`min-h-0 flex-1`), and a last row (`shrink-0 px-5 py-3`) holds `<AppVersion>`, in line with the menu's icons.

## Data and interfaces

`GET /api/updates` (signed-in users), new field:

```json
{ "app_version": "0.23.1", "app": null, "runner": { "latest": "0.10.1", "url": "…" } }
```

- `app_version`: always present; the value of the `APP_VERSION` setting (`"dev"` when run from source).
- `app` and `runner`: unchanged.

No database change, no new setting, no new endpoint.

## Error handling and edge cases

- **Loading or a failed request**: nothing is drawn; the Collapse row keeps its height, so nothing jumps.
- **Old response without the field** (a page open during an upgrade): treated as no version; it appears at the next 15-minute refresh.
- **`APP_VERSION` with a leading `v`**: the label is still `v0.23.1`, never `vv0.23.1`.
- **An unusual `APP_VERSION`** set by hand: shown as plain text, cut with an ellipsis at about 12 characters, the full text in its `title`.
- **A version that was never published as a release**: the link leads to GitHub's "not found" page. Accepted: release images always have a release page.
- **Members**: receive `app_version` only. The test that members never get the latest release stays.
- **Not signed in**: `/api/updates` needs a session, so the login page shows no version.

## Testing

- **Backend** (`backend/tests/updates/test_router.py`): the existing exact-body checks gain `app_version`; a member gets `app_version` and still `app: null`; `dev` is passed through; the version is returned when the organization is not set up yet.
- **Frontend unit** (Vitest):
  - `lib/__tests__/versions.test.ts`: `versionLabel` and `releaseUrl` for `0.23.1`, `v0.23.1`, `dev`, `0.24.0-dev+abc`, empty.
  - New `components/shell/__tests__/AppVersion.test.tsx`: a release renders a link with the right `href`, name and `target`; `dev` renders text and no link; no version renders nothing.
  - `DesktopSidebar.test.tsx`: the version is in the footer; it carries the hidden-label classes when collapsed; the Collapse button still toggles and a click on the version does not.
- **Browser** (Playwright, `frontend/e2e/layout.spec.ts`): the e2e stack is built from source, so a member sees `dev` as plain text in the sidebar footer, and in the phone menu at a phone width.
- Checks before merging: `uv run pytest` for the backend through `megoocolab-runner services run test`, then `npx tsc --noEmit`, `npx eslint` on the changed files, `npm test`, and the Playwright run.

## Out of scope

- The runner's version (it is already shown per agent, with its own update arrow).
- Any change to the Update pill, the update check, or who is told about a newer release.
- An "About" page or card, a changelog inside the app, and the version on the login page.
- The commit hash or build date.
