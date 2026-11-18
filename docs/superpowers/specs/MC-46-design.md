# MC-46 design: unread notifications in the browser tab

## Goal

When the signed-in person has unread notifications, the MegooColab tab shows it: the favicon carries a small red bell badge and the tab title starts with the unread count, for example `(3) Projects · MegooColab`. Someone working in another tab sees at a glance that MegooColab needs them. With nothing unread, the tab looks as it does today.

The approved look is mockup v2.

## Decisions

| Question | Answer | Why |
|---|---|---|
| What does the tab show? | A **small red bell badge** on the favicon **and the count in the tab title** (human's answer). | The badge catches the eye; the title gives the number, which is not readable inside a 16 px icon. Rejected: plain red dot, count drawn inside the icon. |
| When does it show? | **Whenever the unread count is above 0**, also while the tab is in front (human's answer). | It always agrees with the header bell and needs no visibility tracking. Rejected: only while the tab is hidden; only for notifications that arrived while away. |
| How is the badged icon made? | **Drawn in the browser** on a canvas, over the real favicon (human's answer). | No new image files; a new logo is followed automatically. Rejected: a second, ready-made icon file (must be redrawn by hand, and the repository has no image tooling). |
| Other tabs after reading? | **Fixed in this task** (human's answer): the two mark-as-read endpoints send the live event `notification.read`. | Without it, a second tab or device would keep its badge and `(3)` after everything is read. |
| A switch to turn it off? | None. | Not asked for; the mark is silent and small. See "Out of scope". |

The count in the title uses the bell's rule: the exact number up to 99, then `99+`.

## Architecture

The change is mostly frontend. The unread count already exists as one shared query (`useUnreadCount`, key `["notifications", "count"]`) that the header bell uses and that every `notification.*` live event refreshes, also in a background tab. The new code only reads that count and paints the tab.

**1. `frontend/src/lib/favicon.ts` (new): the favicon mark.** One small module with one purpose: switch the tab's icon between the normal and the badged image.

- `setFaviconBadge(on: boolean): void` is the whole interface.
- On: it loads the page's own icon (the PNG `link[rel~="icon"]` that Next.js renders from `app/icon.png`), draws it on a 64×64 canvas, clears a thin ring around the badge area so the badge stands apart on any tab colour, draws a red circle (`#ef4444`) in the top-right corner with a white bell inside (geometry as in mockup v2), and turns the canvas into a PNG data URL. The data URL is made once per page load and kept in the module.
- It then points every `link[rel~="icon"]` in `<head>` at the data URL, remembering each link's original `href` in a data attribute. The Apple touch icon and the PWA manifest icons are not `rel="icon"` and stay untouched.
- Off: it puts the remembered `href`s back.
- The image loads asynchronously, so the module keeps the state it was last asked for and applies the drawing only if the badge is still wanted when the image is ready.

**2. `frontend/src/lib/title.ts` (changed): the count in the title.** The module already owns `document.title` through `apply()`. It gets a module-level unread count and an exported `setTitleCount(count: number)`, which stores the count and calls `apply()`. `apply()` puts `(N) ` or `(99+) ` in front of the title it already computes when the count is above 0. `pageTitle()`, `usePageTitle` and `useRecordTitle` keep their signatures, so the 49 pages that set a title need no change, and a page change keeps the prefix.

**3. `frontend/src/components/notifications/TabBadge.tsx` (new): the connection.** A component that renders nothing. It reads `useUnreadCount()` and, in an effect, calls `setFaviconBadge(count > 0)` and `setTitleCount(count)`. Its cleanup calls `setFaviconBadge(false)` and `setTitleCount(0)`.

**4. `frontend/src/app/(app)/layout.tsx` (changed).** Renders `<TabBadge />` in the signed-in branch, next to `<NavRecorder />`. It is therefore mounted only once the user is known (no unread-count request before sign-in is checked), and it unmounts on sign-out, which restores the normal favicon and title on the sign-in pages.

**5. `backend/app/notifications/router.py` (changed): tell the other tabs.**

- `mark_read`: when the notification was unread, publish `Event(type="notification.read", user_id=user.id)` before the commit.
- `mark_all_read`: publish the same event when the update changed at least one row.

`read_by_acting` in `service.py` already sends this event, and `realtime.ts` already turns any `notification.*` event into a refresh of `["notifications"]` (and the dashboard counts). So every open tab and device of that person refreshes its count, and with it the bell, the favicon and the title. The tab that did the reading also refreshes through its own `onSettled`, as today; the second refresh is harmless.

**6. Docs.** One sentence each in `README.md` (the paragraph on `frontend/e2e/notifications.spec.ts`) and `docs/install.md` (next to the sentence about the chime).

## Data and interfaces

- No new model, endpoint, setting or stored value. No API schema change, so `npm run gen:api` is not needed.
- New frontend exports: `setFaviconBadge(on)` in `lib/favicon.ts`, `setTitleCount(count)` in `lib/title.ts`, `TabBadge` in `components/notifications/TabBadge.tsx`.
- The live event `notification.read` (existing type, `user_id` only) is now also sent by `POST /api/notifications/{id}/read` and `POST /api/notifications/read-all`.

## Error handling and edge cases

- **Drawing fails** (the icon doesn't load, no 2D canvas, `toDataURL` throws): the favicon stays as it is, nothing is thrown, and the title count still shows. A later change of the count tries again.
- **The count drops to 0 before the icon has loaded**: the late drawing is not applied.
- **Count unknown** (query loading or failed): treated as 0, as the bell does.
- **Client-side navigation**: the icon links belong to the root layout and are the same on every page. The browser test checks that the badge survives a page change; if Next.js turns out to rewrite the links, `TabBadge` re-applies the badge after navigation (the plan settles this with the real framework).
- **Several MegooColab tabs**: each tab paints itself from the same count; no coordination is needed (unlike the chime).
- **Live socket reconnect**: the existing refetch-everything on reconnect brings the count, and so the mark, up to date.
- **Browsers that ignore a favicon changed by the page** (Safari is known for it): the badge may not show there; the title count still does. Nothing breaks.
- **Already-read notification marked read again, or "Mark all read" with nothing unread**: no event is sent.
- **Installed app (PWA)**: a standalone window has no tab; the code runs but changes nothing visible. The app icon is not touched.

## Testing

- **Vitest, `lib/__tests__/favicon.test.ts`** (canvas and `Image` stubbed, since jsdom has neither): on → every `rel="icon"` link gets the data URL and the Apple touch icon is untouched; off → the original `href`s are back; a failed image load leaves the links alone and throws nothing; off before the image loads → links unchanged; the drawing happens once for repeated on/off.
- **Vitest, `lib/__tests__/title.test.tsx`** (extended): `(3) ` prefix, `(99+) ` above 99, no prefix at 0, the prefix stays when the page title changes and on the bare `MegooColab` title.
- **Vitest, `components/notifications/__tests__/TabBadge.test.tsx`**: with the count query answering 0, 2 and then 0, the component calls the two setters accordingly; unmounting clears both.
- **Pytest, `backend/tests/notifications/test_core.py`** (extended, in the style of `test_live_event_per_user`): `mark_read` publishes `notification.read` for the owner once, not for an already-read row, not on another person's 404; `read-all` publishes only when something was unread.
- **Playwright, `frontend/e2e/notifications.spec.ts`** (extended): when Bea's bell shows 1, her tab title starts with `(1) ` and the icon link is a `data:image/png` URL, also after a page change; she opens a second tab, uses "Mark all read" in the first, and the second tab's title loses the prefix and its icon link returns to the original (this covers the backend event end to end).
- The usual frontend chain (vitest, `tsc --noEmit`, eslint) and backend `uv run pytest` for the touched areas. No browser test asserts a tab title today, so the prefix breaks none.

## Out of scope

- A setting to turn the badge or the count off.
- The count drawn inside the favicon, animation or blinking.
- Showing the mark only while the tab is in the background.
- A badge on the installed app's icon (`navigator.setAppBadge`), the Apple touch icon and the manifest icons.
- Changes to the chime, to push, email or Telegram notifications, and to which notifications are created.
