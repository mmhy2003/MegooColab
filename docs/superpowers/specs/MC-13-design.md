# MC-13 design: resize the task drawer by dragging its edge

## Goal

On a desktop, a person can drag the left edge of the task drawer (opened from the board or the backlog) to make it wider or narrower. The width they chose is kept in their browser and used the next time a drawer opens.

This design goes with **mockup v2**.

## Decisions

- **Narrowest width is 720 px, and the task keeps its two columns** (your answer). The task's own layout is not touched. Rejected: narrowing down to 480 px with the details folding above the task. It needs the task view's breakpoints to follow the drawer's width instead of the window's, and a narrow drawer gains little because the page behind it is blurred and can't be used while the drawer is open.
- **Widest width is the window's width less 48 px.** A strip of the page stays visible, so it still reads as a drawer and the edge stays easy to grab. "Open full page" already covers the whole window.
- **Default width is 896 px**, which is today's width (`max-w-4xl`). Someone who never drags sees no change on a window of 944 px or wider.
- **The width is remembered in the browser** (`localStorage`), the way the sidebar, the expanded task and the folded details are. One width is shared by the board and the backlog drawers. Rejected: saving it on the account, which needs a backend change for a preference that depends on the screen in use.
- **Desktop only: windows 768 px or wider** (Tailwind `md`, the same line the app already uses for "desktop" in `lib/expanded.ts` and the sidebar). Below that the drawer stays full width and has no grip.
- **The grip:** a short muted pill in the middle of the drawer's left edge, always visible. On hover, keyboard focus and while dragging, the whole edge turns cyan (with the theme's glow) and the pill grows. The cursor is `col-resize`. A tooltip says "Drag to resize · double-click to reset".
- **Double-click on the edge resets to 896 px.**
- **Keyboard:** the edge is focusable. Left arrow widens by 32 px, Right arrow narrows by 32 px, Home goes to the narrowest and End to the widest.

## Architecture

All changes are in `frontend/`. There is no backend change.

- **`src/components/task/drawerWidth.ts` (new).** The constants (`DRAWER_WIDTH_KEY = "tasks.drawerWidth"`, default 896, minimum 720, margin 48, step 32), a pure `clampDrawerWidth(width, windowWidth)`, and a `useDrawerWidth()` hook built on `useStoredState(..., "local")` from `lib/stored.ts`. It follows `fillWindow.ts`, which sits next to the task components in the same way.
- **`src/components/task/DrawerResizeHandle.tsx` (new).** The edge: a `role="separator"` element with `aria-orientation="vertical"`, `aria-label="Resize task"`, `aria-valuemin/max/now` and `tabIndex=0`, wrapped in the existing `Hint`. It owns the pointer, double-click and key handling and reports through three callbacks: a live width while dragging, a committed width, and a reset. It is hidden below `md`.
- **`src/components/task/TaskDrawer.tsx` (modify).** Uses the hook, renders the handle inside the panel, and gives the panel its width through a CSS variable that applies from `md` up, together with a CSS minimum (720 px) and maximum (`100vw - 3rem`). Below `md` the panel stays `w-full`. The fixed `max-w-4xl` goes away.

How a drag works:

1. On pointer down the handle captures the pointer and notes the pointer's x and the panel's current width. Capturing keeps the drag going when the pointer passes over a mockup's iframe. The default action is prevented so no text gets selected.
2. On pointer move the new width is the start width plus how far the pointer moved left, clamped. It is written straight to the panel's CSS variable, not to React state, so the task inside (a long activity list, editors) does not re-render on every move.
3. On pointer up the final width goes to state and to `localStorage`, once.

The stored number is what the person chose. The clamp is applied when it is used, in CSS as well as in the handler, so making the window smaller squeezes the drawer without any script, and making it larger again brings the chosen width back.

Nothing inside the drawer needs to change: the mockup frame is `w-full`, and the jump buttons and the comment box already follow their container's size with `ResizeObserver`.

## Data and interfaces

- One new `localStorage` key, `tasks.drawerWidth`, holding a number of pixels. No API, model or config change.
- `TaskDrawer`'s props do not change, so the board and backlog pages are not touched.

## Error handling and edge cases

- **Storage blocked or holding something else** (a private window, a hand edit): `useStoredState` already falls back to the default and ignores a value of another type. A number out of range is clamped when used.
- **Windows 768 to 943 px wide:** the drawer is at most the window less 48 px, where today it can cover the whole width. At exactly 768 px the minimum and maximum meet at 720 px, so the drawer has one size there.
- **The window is resized while the drawer is open:** the CSS limits apply at once. The `aria-value*` numbers are worked out again on the next interaction.
- **Escape** still closes the drawer, also while the edge has focus. A drag that is cut short (pointer cancelled, the drawer closed mid-drag) keeps the last committed width.
- **Touch on a wide screen** (a tablet in landscape): the handle sets `touch-action: none`, so dragging it resizes and does not scroll.
- **Reduced motion:** only colours and the pill's height animate, and the existing global rule already shortens those.

## Testing

- **Vitest, `drawerWidth`:** the clamp at both limits and on a window too small for the range; the hook reads a stored width, falls back to 896 on a missing or wrong value, and writes on commit.
- **Vitest, `TaskDrawer` (extends `__tests__/TaskDrawer.test.tsx`):** the separator is present with its label and values; arrow keys, Home and End change the width and store it; double-click goes back to 896 and stores it; a pointer down, move and up changes the panel's width and stores it once, on release; the existing tests (stays open on an outside click, closes on ✕ and Escape) still pass.
- **Playwright, a step added to the drawer part of `e2e/popups.spec.ts`:** drag the edge with the mouse, check that the drawer is wider, close and reopen it, and check that the width was kept.
- Checks before merging, as `AGENTS.md` lists them: `npx tsc --noEmit`, `npx eslint` on the changed files, `npm test`, and the browser tests on a fresh stack.

## Out of scope

- Folding the task into one column in a narrow drawer (the option you turned down).
- Resizing anything else: the sidebar, the task's own page, chats, dialogs.
- Keeping the width on the account or sharing it between browsers.
- A width per project or per page.
- Resizing on phones.
