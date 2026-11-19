# MC-68 plan: show the current version in the sidebar footer

**Goal:** everyone who is signed in sees the server's MegooColab version ("v0.23.1") at the foot of the sidebar. A release's version links to its notes on GitHub. A build from source shows a plain `dev`.

**Architecture:** `GET /api/updates` gets one new field, `app_version`, for every signed-in user. The frontend already loads this endpoint through `useUpdates()` and refreshes it every 15 minutes. Two pure helpers in `lib/versions.ts` turn the version into a label and a release URL. A new `AppVersion` component draws it on the Collapse row of the desktop sidebar and on a last row of the phone menu.

## File map

| File | Change |
|---|---|
| `backend/app/updates/schemas.py` | `UpdatesOut.app_version: str` (required) |
| `backend/app/updates/router.py` | `get_updates` sets `app_version` on both returns; docstring updated |
| `backend/tests/updates/test_router.py` | exact bodies gain `app_version`; new tests for everyone, `dev`, and no organization |
| `frontend/src/lib/versions.ts` | `versionLabel`, `releaseUrl` |
| `frontend/src/lib/__tests__/versions.test.ts` | tests for the two helpers |
| `frontend/src/lib/api-types.ts` | regenerated (`npm run gen:api`) |
| `frontend/src/components/shell/AppVersion.tsx` | new: the version as a link or as text |
| `frontend/src/components/shell/__tests__/AppVersion.test.tsx` | new |
| `frontend/src/components/shell/DesktopSidebar.tsx` | the Collapse button and `AppVersion` share one row |
| `frontend/src/components/shell/__tests__/DesktopSidebar.test.tsx` | footer tests; the fetch mock answers `/api/updates` |
| `frontend/src/app/(app)/layout.tsx` | the phone menu's aside becomes a column with a version row |
| `frontend/e2e/layout.spec.ts` | a member sees `dev` on the desktop and in the phone menu |

## Code referred to by the steps

### A. `frontend/src/lib/versions.ts` (append below `isNewer`)

```ts
const RELEASES = "https://github.com/mmhy2003/MegooColab/releases/tag/";

/** The running version as shown: a release as "v0.23.1" (never "vv0.23.1"); anything else (dev, 0.24.0-dev+abc)
 * as it is, trimmed. */
export function versionLabel(v?: string | null): string {
  const r = parseVersion(v);
  return r ? `v${r.join(".")}` : (v ?? "").trim();
}

/** The release's notes on GitHub; null for a build from source, which has no release page. */
export function releaseUrl(v?: string | null): string | null {
  const r = parseVersion(v);
  return r ? `${RELEASES}v${r.join(".")}` : null;
}
```

### B. `frontend/src/components/shell/AppVersion.tsx`

```tsx
"use client";

import { Hint } from "@/components/ui/Hint";
import { useUpdates } from "@/lib/updates";
import { releaseUrl, versionLabel } from "@/lib/versions";

const LOOK = "text-xs whitespace-nowrap text-muted-foreground tabular-nums no-underline";

/** The MegooColab version the server runs, for everyone signed in ("I'm on v0.23.1" in a bug report). A release
 * links to its notes on GitHub; a build from source ("dev") has none, so it is plain text. Nothing while the version
 * is not known (loading, a failed request, a server older than this page). */
export function AppVersion({ className = "" }: { className?: string }) {
  const version = useUpdates().data?.app_version;
  const label = versionLabel(version);
  if (!label) return null;
  const url = releaseUrl(version);
  if (!url) {
    return (
      <span title={label} className={`inline-block max-w-[12ch] truncate align-middle ${LOOK} ${className}`}>
        <span className="sr-only">MegooColab </span>
        {label}
      </span>
    );
  }
  const number = label.slice(1);
  return (
    <Hint label={`MegooColab ${number}: release notes`}>
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        aria-label={`MegooColab ${number}, release notes (opens in a new tab)`}
        className={`${LOOK} hover:text-cyan-ink hover:underline focus-visible:text-cyan-ink focus-visible:underline ${className}`}
      >
        {label}
      </a>
    </Hint>
  );
}
```

### C. DesktopSidebar footer (replaces the `<Hint>…</Hint>` block at the end of the inner div)

```tsx
{/* the Collapse button keeps its width; the version sits at the right of the same row and, like every label,
    hides on the closed rail (tabbing onto its link opens the rail) */}
<div className="m-2 flex items-center">
  <Hint label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
    <button
      type="button"
      aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      onClick={toggle}
      className="flex items-center gap-2 rounded px-3 py-2 text-sm whitespace-nowrap text-muted-foreground hover:bg-surface hover:text-cyan"
    >
      <Icon size={16} aria-hidden className="shrink-0" />
      <span className={collapsed ? LABEL_HIDDEN : ""}>{collapsed ? "Expand" : "Collapse"}</span>
    </button>
  </Hint>
  <AppVersion className={`ml-auto pr-3 ${collapsed ? LABEL_HIDDEN : ""}`} />
</div>
```

### D. Phone menu in `frontend/src/app/(app)/layout.tsx`

```tsx
<aside className="relative flex h-full w-64 flex-col border-r border-line bg-surface">
  <div className="min-h-0 flex-1">
    <Sidebar user={user} onNavigate={() => setMenuOpen(false)} />
  </div>
  {/* px-5: in line with the menu's icons (the nav's p-2 plus the links' px-3) */}
  <div className="shrink-0 px-5 py-3">
    <AppVersion />
  </div>
</aside>
```

### E. Playwright test, appended to `frontend/e2e/layout.spec.ts`

```ts
test("everyone signed in sees the server's version at the foot of the sidebar", async ({ page, browser }) => {
  // the e2e stack is built from source, so the server runs "dev": plain text, no release link
  await setupOrSignIn(page);
  const web = { "X-Megoo-Client": "web" };
  const email = `vera-${Date.now()}@acme.io`; // any stack: fresh or not
  const invite = await page.request.post("/api/admin/users/invite", {
    data: { email, name: "Vera Version", role: "member" },
    headers: web,
  });
  expect(invite.ok(), await invite.text()).toBeTruthy();
  const token = (await invite.json()).invite_url.split("/invite/")[1];
  const ctx = await browser.newContext({ baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080" });
  try {
    const accepted = await ctx.request.post("/api/auth/accept-invite", {
      data: { token, password: "vera-password-123" },
      headers: web,
    });
    expect(accepted.ok(), await accepted.text()).toBeTruthy();
    const member = await ctx.newPage();
    await member.setViewportSize({ width: 1280, height: 800 });
    await member.goto("/projects");
    const aside = member.locator("aside").first();
    await expect(aside.getByText("MegooColab dev", { exact: true })).toBeVisible();
    await expect(aside.getByRole("link", { name: /MegooColab/ })).toHaveCount(0);

    await member.setViewportSize({ width: 375, height: 700 });
    await member.getByRole("button", { name: "Open menu" }).click();
    const menu = member.getByRole("dialog", { name: "Menu" });
    await expect(menu.getByText("MegooColab dev", { exact: true })).toBeInViewport();
  } finally {
    await ctx.close();
  }
});
```

## Steps

### 1. Backend: GET /api/updates sends the running version to everyone

**Files:** `backend/app/updates/schemas.py`, `backend/app/updates/router.py`, `backend/tests/updates/test_router.py`.

**Tests first** (`backend/tests/updates/test_router.py`):
- `test_an_admin_is_told_of_a_newer_server`: the expected body gains `"app_version": "0.1.0"`.
- `test_a_member_is_not_told_of_the_server`: expected `{"app_version": "0.1.0", "app": None, "runner": {...}}`. A member still gets `app: None`.
- `test_nothing_known_yet`: expected `{"app_version": "0.1.0", "app": None, "runner": None}`.
- New `test_everyone_gets_the_running_version`, parametrized over `role` in (`Role.admin`, `Role.member`) and `app_version` in (`"dev"`, `"0.2.0"`, `"0.24.0-dev+abc"`), with the `stored` fixture: `body["app_version"] == app_version`.
- New `test_the_version_comes_before_the_organization_is_set_up` (no `stored`, no `OrgSettings` row): `_updates(..., role=Role.member, app_version="0.1.0") == {"app_version": "0.1.0", "app": None, "runner": None}`.

Run from `backend/`: `megoocolab-runner services run test -- uv run pytest tests/updates/test_router.py -q`. The tests fail because `app_version` is missing from the body.

**Implement:**
- `schemas.py`: add `app_version: str  # the version this server runs ("dev" from source); for everyone signed in` as the first field of `UpdatesOut`. It has no default, so the OpenAPI type is required.
- `router.py`: read `current = get_settings().app_version` before the `org is None` check, return `UpdatesOut(app_version=current)` there, and `UpdatesOut(app_version=current, app=app, runner=runner)` at the end. Docstring: "The running version, for everyone signed in, and the latest releases as the update check last found them. The server's own update is for admins only: they are the ones who can install it." Leave the admin rule for `app` as it is.

Run again: everything passes. Then run `megoocolab-runner services run test -- uv run pytest tests/updates -q`.

**Commit:** `feat(updates): GET /api/updates sends the running version to everyone (MC-68)`

### 2. Frontend: versionLabel and releaseUrl helpers

**Files:** `frontend/src/lib/versions.ts`, `frontend/src/lib/__tests__/versions.test.ts`.

**Tests first:** add to the existing `describe("versions")` (and update the import):
- `versionLabel`: `"0.23.1"` gives `"v0.23.1"`, `"v0.23.1"` gives `"v0.23.1"`, `" dev "` gives `"dev"`, `"0.24.0-dev+abc"` gives `"0.24.0-dev+abc"`; `""`, `null` and `undefined` give `""`.
- `releaseUrl`: `"0.23.1"` and `"v0.23.1"` give `"https://github.com/mmhy2003/MegooColab/releases/tag/v0.23.1"`; `"dev"`, `"0.24.0-dev+abc"`, `""` and `null` give `null`.

Run from `frontend/`: `npx vitest run src/lib/__tests__/versions.test.ts`. It fails because the exports do not exist.

**Implement:** code block A in the plan, built on `parseVersion`. Run again: pass. Then `npx tsc --noEmit` and `npx eslint src/lib/versions.ts src/lib/__tests__/versions.test.ts`.

**Commit:** `feat(versions): label and release link for the running version (MC-68)`

### 3. Frontend: AppVersion component

**Files:** `frontend/src/lib/api-types.ts` (regenerated), new `frontend/src/components/shell/AppVersion.tsx`, new `frontend/src/components/shell/__tests__/AppVersion.test.tsx`.

**Regenerate types** from `frontend/`: `npm ci` if needed, then `npm run gen:api`. `UpdatesOut` now has `app_version: string`. Commit only the `api-types.ts` change; `openapi.json` is not tracked.

**Tests first** (use the same pattern as `UpdatePill.test.tsx`: stub `fetch` with the body, `QueryClientProvider` with `retry: false`):
- "links a release to its notes": body `{app_version: "0.23.1", app: null, runner: null}`. `await screen.findByRole("link", { name: "MegooColab 0.23.1, release notes (opens in a new tab)" })` has `href` `https://github.com/mmhy2003/MegooColab/releases/tag/v0.23.1`, `target="_blank"`, `rel="noreferrer"`, and text `v0.23.1`.
- "does not double the v": `app_version: "v0.23.1"` shows the text `v0.23.1`.
- "shows a build from source as plain text": `app_version: "dev"`. `await screen.findByText("dev")`, and `screen.queryByRole("link")` is null. The element has `title="dev"` and its text is `MegooColab dev` (the visually hidden prefix).
- "draws nothing without a version": body `{app: null, runner: null}` (an old server). After `await new Promise((r) => setTimeout(r, 20))`, `container` is empty. A fetch that answers 500 also leaves it empty.
- "passes its className on": `className="ml-auto"` ends up on the link.

Run `npx vitest run src/components/shell/__tests__/AppVersion.test.tsx`. It fails because the module is not found.

**Implement:** code block B in the plan exactly. Run again: pass. Then `npx tsc --noEmit` and `npx eslint` on the two new files.

**Commit:** `feat(shell): AppVersion shows the server's version, linked to its release notes (MC-68)`

### 4. Desktop sidebar: the version on the Collapse row

**Files:** `frontend/src/components/shell/DesktopSidebar.tsx`, `frontend/src/components/shell/__tests__/DesktopSidebar.test.tsx`.

**Tests first:**
- Change the `beforeEach` fetch stub to answer by URL: `vi.fn(async (url: RequestInfo | URL) => new Response(JSON.stringify(String(url).includes("/api/updates") ? { app_version: "0.23.1", app: null, runner: null } : { needs_you: 0 }), { status: 200 }))`.
- "shows the version at the foot, after the Collapse button": `const v = await screen.findByRole("link", { name: /MegooColab 0\.23\.1/ })`. `v` is inside `aside()`, its text is `v0.23.1`, and `screen.getByRole("button", { name: "Collapse sidebar" }).compareDocumentPosition(v) & Node.DOCUMENT_POSITION_FOLLOWING` is truthy. `v.className` contains `ml-auto` and not `opacity-0`.
- "hides the version on the closed rail, like the labels": with `localStorage` set to collapsed, the link's className contains `opacity-0` and `group-hover/side:opacity-100`.
- "a click on the version does not fold the sidebar": `fireEvent.click(link)`; `data-collapsed` stays `"false"`. The Collapse button still toggles (the existing test covers that).

Run `npx vitest run src/components/shell/__tests__/DesktopSidebar.test.tsx`. The new tests fail.

**Implement:** replace the Hint/button block with code block C in the plan. The button loses `m-2` because the row carries it now. Import `AppVersion` from `@/components/shell/AppVersion`. Run again: everything passes.

Then `npx tsc --noEmit`, `npx eslint` on both files, and `npm test` (the whole Vitest suite; the Dashboard 300 ms test is known to be flaky under load).

**Commit:** `feat(shell): the version sits at the foot of the desktop sidebar (MC-68)`

### 5. Phone menu row and browser test

**Files:** `frontend/src/app/(app)/layout.tsx`, `frontend/e2e/layout.spec.ts`.

**Browser test first:** append code block E in the plan to `frontend/e2e/layout.spec.ts`. It reuses the existing `setupOrSignIn` import. Run from `frontend/`: `megoocolab-runner services run e2e -- npx playwright test e2e/layout.spec.ts --reporter=line`. The new test fails at the phone-menu assertion; the desktop part already passes after step 4.

**Implement:** in `layout.tsx`, replace the phone menu's `<aside>` with code block D in the plan and import `AppVersion`. The aside becomes `flex flex-col`; `Sidebar` fills it inside `min-h-0 flex-1`, so its links still scroll under a fixed logo. Run the same Playwright command again: the whole `layout.spec.ts` passes, including "the logo stays at the top of the sidebar while its menu scrolls".

Then `npx tsc --noEmit`, `npx eslint 'src/app/(app)/layout.tsx' e2e/layout.spec.ts`, and `npm test`.

**Commit:** `feat(shell): the phone menu shows the version too (MC-68)`

## Final verification

From `backend/`:
- `megoocolab-runner services run test -- uv run pytest -q -n auto`

From `frontend/`:
- `npx tsc --noEmit`
- `npx eslint src/lib/versions.ts src/lib/__tests__/versions.test.ts src/components/shell/AppVersion.tsx src/components/shell/__tests__/AppVersion.test.tsx src/components/shell/DesktopSidebar.tsx src/components/shell/__tests__/DesktopSidebar.test.tsx 'src/app/(app)/layout.tsx' e2e/layout.spec.ts`
- `npm test`
- `megoocolab-runner services run e2e -- npx playwright test --reporter=line`

Known flaky or pre-existing failures (search tests that need Meilisearch, rate-limit tests, the Dashboard 300 ms test) are not regressions.
