# MC-46 plan: unread notifications in the browser tab

## Goal
While the signed-in person has unread notifications, the MegooColab tab shows a small red bell badge on the favicon and the unread count before the title (`(3) Projects · MegooColab`, `(99+) …` above 99). Reading everything in one tab or device clears the mark in all the others.

## Architecture
The unread count already lives in one query (`useUnreadCount`, key `["notifications","count"]`, `frontend/src/lib/notifications.ts:43`), and every `notification.*` live event refreshes it (`frontend/src/lib/realtime.ts:52`). A new component, `TabBadge`, reads that count and paints the tab through two small modules: `lib/favicon.ts` (new, canvas-drawn badged icon) and `lib/title.ts` (extended with a count prefix). On the backend, the two mark-as-read endpoints publish the existing `notification.read` event, so other tabs refetch the count.

## Facts checked in the code
- `frontend/src/lib/title.ts`: `apply()` computes `document.title` from the `shown` map; `pageTitle`, `usePageTitle`, `useRecordTitle` are exported. Tests: `frontend/src/lib/__tests__/title.test.tsx` (its `afterEach` resets `document.title`).
- `frontend/src/app/` has both `favicon.ico` and `icon.png`. Next.js renders a `<link rel="icon">` for each: the ICO one (`/favicon.ico`) and a PNG one (`type="image/png"`, `/icon.png?…`). `apple-icon.png` renders as `rel="apple-touch-icon"` and is untouched by a `rel~="icon"` selector. Manifest icons (`app/manifest.ts`) are untouched.
- `frontend/src/app/(app)/layout.tsx`: the signed-in branch renders `<Suspense fallback={null}><NavRecorder /></Suspense>` first; `TabBadge` goes right after it.
- `NotificationBell` reads `useUnreadCount().data?.count ?? 0` and shows `99+` above 99: same rule for the title.
- Vitest: jsdom, `frontend/vitest.config.mts`, setup `frontend/vitest.setup.ts` (cleanup after each). Query tests stub `fetch` with `vi.stubGlobal` and wrap with a `QueryClient({ defaultOptions: { queries: { retry: false } } })` (see `components/notifications/__tests__/Notifications.test.tsx`). `next/navigation` is mocked with `vi.mock("next/navigation", () => ({ … }))`.
- Backend: `backend/app/notifications/router.py` `mark_read` / `mark_all_read`; `Event` and `publish` come from `app.core.events`. `service.read_by_acting` already publishes `Event(type="notification.read", user_id=…)` when `rowcount` is non-zero. Tests: `backend/tests/notifications/test_core.py` (`_world`, `test_live_event_per_user` monkeypatches `service.publish`; other tests patch a module's imported `publish` the same way).
- E2E: `frontend/e2e/notifications.spec.ts`, one test "notifications reach the right people"; Bea's context is `bea.ctx`, her page `beaPage`, helpers `bell(page)`, `unread()`, `readAll()` (section 6). The sidebar is `nav[aria-label="Main"]` with links "Projects", "Teams", ….
- Checks (AGENTS.md): frontend in `frontend/`: `npx vitest run <file>`, `npx tsc --noEmit`, `npx eslint <changed files>`, `npm test`; backend in `backend/`: `uv run pytest <path>` (never two pytest runs at once). Commits: `type(area): sentence`, body explains why, plus the co-author line. No `npm run gen:api` (no API schema change).

## File map
| File | Change | Responsibility |
|---|---|---|
| `backend/app/notifications/router.py` | modify | `mark_read` / `mark_all_read` publish `notification.read` when something became read |
| `backend/tests/notifications/test_core.py` | modify | `test_mark_read_tells_other_tabs` |
| `frontend/src/lib/title.ts` | modify | module-level unread count, `setTitleCount(count)`, `(N) ` prefix in `apply()` |
| `frontend/src/lib/__tests__/title.test.tsx` | modify | prefix tests |
| `frontend/src/lib/favicon.ts` | create | `setFaviconBadge(on)`: draw the badged icon once, point/restore `rel~="icon"` links |
| `frontend/src/lib/__tests__/favicon.test.ts` | create | favicon tests with stubbed canvas and `Image` |
| `frontend/src/components/notifications/TabBadge.tsx` | create | reads `useUnreadCount`, calls both setters; clears on unmount |
| `frontend/src/components/notifications/__tests__/TabBadge.test.tsx` | create | TabBadge tests |
| `frontend/src/app/(app)/layout.tsx` | modify | render `<TabBadge />` in the signed-in branch |
| `frontend/e2e/notifications.spec.ts` | modify | section 7: title prefix, badged icon, survives page change, cleared in a second tab |
| `README.md`, `docs/install.md` | modify | one sentence each |

## Steps

### 1. Backend: mark-as-read endpoints publish notification.read
**Test first** — add to `backend/tests/notifications/test_core.py` (after `test_list_read_and_unread_count`), importing `from app.notifications import router as notify_router`:

```python
async def test_mark_read_tells_other_tabs(client_factory, db, monkeypatch):
    """Reading in one tab tells the person's other tabs and devices, so their bell (and tab badge) follows."""
    _manager, bea, _m, b, _task = await _world(client_factory, db)
    async with SessionLocal() as s:
        for i in range(2):
            s.add(Notification(user_id=bea.id, kind="assigned", title=f"r{i}", body="", link="/x"))
        await s.commit()
    first, second = [n for n in await _rows(bea.id) if n.title in ("r0", "r1")]
    seen = []
    real = notify_router.publish

    async def capture(session, event):
        seen.append((event.type, event.user_id))
        await real(session, event)

    monkeypatch.setattr(notify_router, "publish", capture)
    other = client_factory()
    await login(other, await make_user(db))
    assert (await other.post(f"/api/notifications/{first.id}/read")).status_code == 404
    assert seen == []  # someone else's notification: nothing read, nothing sent
    assert (await b.post(f"/api/notifications/{first.id}/read")).status_code == 204
    assert seen == [("notification.read", bea.id)]
    assert (await b.post(f"/api/notifications/{first.id}/read")).status_code == 204
    assert len(seen) == 1  # already read: no event
    assert (await b.post("/api/notifications/read-all")).status_code == 204
    assert seen == [("notification.read", bea.id)] * 2  # second (and any other unread) became read
    assert (await b.post("/api/notifications/read-all")).status_code == 204
    assert len(seen) == 2  # nothing unread: no event
    assert second
```
Run `cd backend; uv run pytest tests/notifications/test_core.py -k mark_read_tells -q` → fails with `AttributeError: … has no attribute 'publish'` (router doesn't import it yet).

**Implement** in `router.py`: add `from app.core.events import Event, publish`. In `mark_read`, inside `if n.read_at is None:` after setting `read_at` and before `commit`: `await publish(db, Event(type="notification.read", user_id=user.id))`. In `mark_all_read`: `done = await db.execute(update(...)...)`; `if done.rowcount: await publish(db, Event(type="notification.read", user_id=user.id))`; then `commit`. Comment: `# the person's other tabs and devices refresh their count` (one line). NOTIFY is transactional, so publishing before commit is correct.

Run the test again → passes; then `uv run pytest tests/notifications -q` → all pass.
Commit: `fix(notifications): reading a notification tells the person's other tabs and devices` (body: before, a second tab kept its bell count until reload; MC-46's tab badge needs it).

### 2. Frontend: unread count prefix in the tab title
**Test first** — in `frontend/src/lib/__tests__/title.test.tsx` import `setTitleCount` too, add `setTitleCount(0)` to `afterEach` (before resetting `document.title`), and add `describe("setTitleCount")`:
- "puts the count before the title": render `<Page parts={["Projects"]} />`, `setTitleCount(3)` → `"(3) Projects · MegooColab"`.
- "caps at 99+": `setTitleCount(100)` → `"(99+) Projects · MegooColab"`; `setTitleCount(99)` → `"(99) …"`.
- "no prefix at 0": `setTitleCount(3)` then `setTitleCount(0)` → `"Projects · MegooColab"`.
- "keeps the prefix when the page changes": with count 2, `rerender(<Page parts={["Teams"]} />)` → `"(2) Teams · MegooColab"`; `unmount()` → `"(2) MegooColab"`.
Run `cd frontend; npx vitest run src/lib/__tests__/title.test.tsx` → fails (`setTitleCount` is not exported).

**Implement** in `title.ts`:
```ts
// unread notifications, shown before the title (TabBadge): "(3) Projects · MegooColab"
let unread = 0;

function apply() {
  …existing loop…
  const count = unread > 99 ? "99+" : String(unread);
  document.title = (unread > 0 ? `(${count}) ` : "") + (top?.title ?? APP_NAME);
}

/** Puts the unread count before the tab's title; 0 takes it away. */
export function setTitleCount(count: number): void {
  unread = count;
  apply();
}
```
Run the test file → passes. `npx tsc --noEmit`, `npx eslint src/lib/title.ts src/lib/__tests__/title.test.tsx`.
Commit: `feat(notifications): the tab title can start with the unread count`.

### 3. Frontend: favicon badge module
Create `frontend/src/lib/favicon.ts` with exactly the code in "Appendix A", and `frontend/src/lib/__tests__/favicon.test.ts` per "Appendix B" (write the test first; run `npx vitest run src/lib/__tests__/favicon.test.ts` → fails because the module does not exist; add the module → passes). `npx tsc --noEmit`; `npx eslint src/lib/favicon.ts src/lib/__tests__/favicon.test.ts`.
Commit: `feat(notifications): draw a bell badge over the favicon`.

### 4. Frontend: TabBadge in the signed-in layout
**Test first** — `frontend/src/components/notifications/__tests__/TabBadge.test.tsx`:
```tsx
vi.mock("next/navigation", () => ({ usePathname: () => "/projects" }));
vi.mock("@/lib/favicon", () => ({ setFaviconBadge: vi.fn() }));
vi.mock("@/lib/title", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/title")>()), setTitleCount: vi.fn() }));
```
One test "marks the tab while anything is unread, and clears it when it goes": mutable `count = 0`; stub `fetch` to answer `/api/notifications/unread-count` with `{ count }`; render `<TabBadge />` in a `QueryClientProvider` with a client you keep. `await waitFor` → last calls `setFaviconBadge(false)`, `setTitleCount(0)`. Set `count = 2`, `await act(() => client.invalidateQueries({ queryKey: ["notifications", "count"] }))` → last calls `(true)`, `(2)`. Back to 0 → `(false)`, `(0)`. Set 5, invalidate, then `unmount()` → last calls `(false)`, `(0)`. Use `vi.mocked(fn).mock.lastCall`. Run `npx vitest run src/components/notifications/__tests__/TabBadge.test.tsx` → fails (no module).

**Implement** `TabBadge.tsx`:
```tsx
"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { setFaviconBadge } from "@/lib/favicon";
import { useUnreadCount } from "@/lib/notifications";
import { setTitleCount } from "@/lib/title";

/** Marks the browser tab while anything is unread: a bell on the favicon and "(3) " before the title. Renders nothing. */
export function TabBadge() {
  const count = useUnreadCount().data?.count ?? 0;
  // a page change may re-render the head's icon links and title: mark them again
  const pathname = usePathname();
  useEffect(() => {
    setFaviconBadge(count > 0);
    setTitleCount(count);
  }, [count, pathname]);
  useEffect(
    () => () => {
      setFaviconBadge(false);
      setTitleCount(0);
    },
    [],
  );
  return null;
}
```
In `frontend/src/app/(app)/layout.tsx` import it and render `<TabBadge />` right after the `NavRecorder` `Suspense` block (signed-in branch only). Run the test → passes; `npm test` (whole suite), `npx tsc --noEmit`, `npx eslint` on the three files.
Commit: `feat(notifications): the browser tab shows unread notifications`.

### 5. E2E and docs
Add section 7 at the end of the test in `frontend/e2e/notifications.spec.ts` (Appendix C). Docs: in `README.md` line 151 append to the paragraph: "While anything is unread, her tab title starts with the count and the favicon carries a bell, also after a page change, and reading everything in one tab clears both in her other tab." In `docs/install.md`, after the chime sentence (ends "…on the same page."): "While anything is unread, the browser tab shows it too: the title starts with the count, such as `(3) Projects · MegooColab`, and the icon carries a small red bell." Run the spec on a fresh `megoo-e2e` stack as AGENTS.md describes (`npx playwright test e2e/notifications.spec.ts --reporter=line`). If the title prefix or the data URL is lost after the client-side page change, fix it in `TabBadge` (it already re-applies on `pathname`), not in the test. `npx eslint e2e/notifications.spec.ts`; `npx tsc --noEmit`.
Commit: `test(notifications): the tab badge and title count, also across tabs`.

## Appendix A — `frontend/src/lib/favicon.ts`
```ts
/**
 * The favicon's unread mark: a small red bell drawn in the browser over the app's own icon. Every `rel="icon"`
 * link points at the drawing while the mark is on and gets its own address back when it goes. The Apple touch icon
 * and the manifest's icons are not `rel="icon"` and stay as they are.
 */

const SIZE = 64;
// the badge: a red circle in the top-right corner, with a gap cut around it so it stands apart on any tab colour
const BADGE = { x: 46, y: 18, r: 16, gap: 3 };
const RED = "#ef4444";

let wanted = false;
let badged: string | null = null; // the drawing, made once per page load
let drawing = false;

function links(): HTMLLinkElement[] {
  return Array.from(document.head.querySelectorAll<HTMLLinkElement>('link[rel~="icon"]'));
}

// the link's own address, also while it points at the drawing
const own = (link: HTMLLinkElement) => link.dataset.megooHref ?? link.getAttribute("href");

function source(): string | null {
  const all = links();
  const png = all.find((l) => l.type === "image/png") ?? all[0];
  return png ? own(png) : null;
}

function point() {
  for (const link of links()) {
    if (wanted && badged) {
      if (link.dataset.megooHref === undefined) link.dataset.megooHref = link.getAttribute("href") ?? "";
      link.href = badged;
    } else if (link.dataset.megooHref !== undefined) {
      link.setAttribute("href", link.dataset.megooHref);
      delete link.dataset.megooHref;
    }
  }
}

function draw(icon: HTMLImageElement): string {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = SIZE;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no 2D canvas");
  ctx.drawImage(icon, 0, 0, SIZE, SIZE);
  const circle = (x: number, y: number, r: number) => {
    ctx.beginPath();
    ctx.arc(x, y, r, 0, 2 * Math.PI);
    ctx.fill();
  };
  ctx.globalCompositeOperation = "destination-out";
  circle(BADGE.x, BADGE.y, BADGE.r + BADGE.gap);
  ctx.globalCompositeOperation = "source-over";
  ctx.fillStyle = RED;
  circle(BADGE.x, BADGE.y, BADGE.r);
  // the bell: body, clapper and knob
  ctx.fillStyle = "#ffffff";
  ctx.beginPath();
  ctx.moveTo(37, 24);
  ctx.lineTo(55, 24);
  ctx.lineTo(52, 20);
  ctx.lineTo(52, 15);
  ctx.arc(46, 15, 6, 0, Math.PI, true);
  ctx.lineTo(40, 20);
  ctx.closePath();
  ctx.fill();
  circle(46, 26.5, 2.5);
  circle(46, 8.5, 1.5);
  return canvas.toDataURL("image/png");
}

/** Shows or hides the bell badge on the tab's icon. Never throws: if it can't draw, the icon stays as it is. */
export function setFaviconBadge(on: boolean): void {
  wanted = on;
  if (!on || badged) {
    point();
    return;
  }
  const src = source();
  if (drawing || !src) return;
  drawing = true;
  const icon = new Image();
  icon.onload = () => {
    drawing = false;
    try {
      badged = draw(icon);
    } catch {
      return;
    }
    point(); // applies only if the badge is still wanted
  };
  icon.onerror = () => {
    drawing = false; // the next change of the count tries again
  };
  icon.src = src;
}
```
(The icon is same-origin, so the canvas is not tainted; `toDataURL` failing is caught all the same.)

## Appendix B — `frontend/src/lib/__tests__/favicon.test.ts`
Setup:
- `beforeEach`: `vi.resetModules()`; `const mod = await import("@/lib/favicon")` (fresh module state per test); fill `document.head` with `<link rel="icon" href="/favicon.ico" sizes="any" type="image/x-icon">`, `<link rel="icon" href="/icon.png?abc" type="image/png" sizes="512x512">`, `<link rel="apple-touch-icon" href="/apple-icon.png?def">`.
- Stub `Image`: `vi.stubGlobal("Image", class { onload: (() => void) | null = null; onerror: (() => void) | null = null; src = ""; constructor() { images.push(this); } })` with a module-level `images` array reset each test.
- Canvas: `const ctx = { drawImage: vi.fn(), beginPath: vi.fn(), arc: vi.fn(), fill: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), closePath: vi.fn(), globalCompositeOperation: "", fillStyle: "" }`; `getContext = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx as never)`; `vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/png;base64,BADGE")`.
- `afterEach`: `vi.restoreAllMocks()`, `vi.unstubAllGlobals()`, `document.head.innerHTML = ""`.
- `const hrefs = () => [...document.head.querySelectorAll("link")].map((l) => l.getAttribute("href"))`.

Tests:
1. "loads the PNG icon and points every icon link at the badge": `setFaviconBadge(true)`; `images[0].src === "/icon.png?abc"`; links unchanged before load; `images[0].onload!()`; `hrefs()` → `["data:image/png;base64,BADGE", "data:image/png;base64,BADGE", "/apple-icon.png?def"]`; `ctx.fillStyle` set to `#ef4444` at some point (assert `ctx.arc` was called with `46, 18, 16`).
2. "off puts the original addresses back": on → load → off → `hrefs()` → `["/favicon.ico", "/icon.png?abc", "/apple-icon.png?def"]`, and no link keeps `data-megoo-href`.
3. "a failed load leaves the links alone and throws nothing": on → `images[0].onerror!()` → hrefs original; `setFaviconBadge(true)` again creates a second `Image` (retry).
4. "no 2D canvas: the icon stays": `getContext.mockReturnValue(null)`; on → onload → no throw, hrefs original.
5. "off before the icon loads: the late drawing is not applied": on → off → `images[0].onload!()` → hrefs original.
6. "draws once for repeated on and off": on → load → off → on → off → on: `images.length === 1`, `getContext` called once, links point at the badge.

## Appendix C — e2e section 7 (end of the test in `notifications.spec.ts`)
```ts
  // 7. while anything is unread, Bea's tab says so: the count before the title and a bell on the favicon, also after
  // a page change; reading everything in one tab clears both in her other tab
  const icons = (p: Page) => p.locator('link[rel~="icon"]').evaluateAll((ls) => ls.map((l) => l.getAttribute("href") ?? ""));
  const badged = async (p: Page) => (await icons(p)).every((h) => h.startsWith("data:image/png"));
  const plain = async (p: Page) => (await icons(p)).every((h) => !h.startsWith("data:"));
  count = await unread();
  expect(count).toBeGreaterThan(0); // section 6 left its mention unread
  await beaPage.goto("/projects");
  await expect(bell(beaPage)).toHaveText(String(count), { timeout: 15_000 });
  await expect(beaPage).toHaveTitle(`(${count}) Projects · MegooColab`);
  await expect.poll(() => badged(beaPage)).toBe(true);
  await beaPage.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Teams", exact: true }).click();
  await expect(beaPage).toHaveURL(/\/teams$/);
  await expect(beaPage).toHaveTitle(new RegExp(`^\\(${count}\\) `));
  await expect.poll(() => badged(beaPage)).toBe(true);
  const other = await bea.ctx.newPage();
  await other.goto("/projects");
  await expect(other).toHaveTitle(`(${count}) Projects · MegooColab`, { timeout: 15_000 });
  await expect.poll(() => badged(other)).toBe(true);
  await bell(beaPage).click();
  await beaPage.getByRole("button", { name: "Mark all read" }).click();
  await expect(other).toHaveTitle("Projects · MegooColab", { timeout: 15_000 }); // told by the server, no reload
  await expect.poll(() => plain(other)).toBe(true);
  await expect(beaPage).not.toHaveTitle(/^\(/);
```
(If `count` were above 99 the title would read `(99+)`; Bea has only a few here.)

## Final verification
- `cd backend; uv run pytest tests/notifications -q`
- `cd frontend; npm test; npx tsc --noEmit; npx eslint src/lib/title.ts src/lib/favicon.ts src/lib/__tests__/title.test.tsx src/lib/__tests__/favicon.test.ts src/components/notifications/TabBadge.tsx src/components/notifications/__tests__/TabBadge.test.tsx 'src/app/(app)/layout.tsx' e2e/notifications.spec.ts`
- On a fresh `megoo-e2e` stack (AGENTS.md "Browser tests"): `cd frontend; npx playwright test e2e/notifications.spec.ts --reporter=line`
- By hand (optional): with unread notifications, the tab shows the red bell and `(N)`; "Mark all read" in one tab clears another.
