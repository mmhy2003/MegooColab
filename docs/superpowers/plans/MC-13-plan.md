# MC-13 plan: resize the task drawer by dragging its edge

## Goal
On a desktop (window ≥ 768 px) a person can drag, double-click or use the keyboard on the task drawer's left edge to change its width (720 px to the window less 48 px, default 896 px). The width is kept in `localStorage` under `tasks.drawerWidth`.

## Architecture
A small module, `frontend/src/components/task/drawerWidth.ts`, holds the constants, a pure clamp and a `useDrawerWidth()` hook built on `useStoredState(..., "local")`. A new `DrawerResizeHandle` (a `role="separator"` element wrapped in `Hint`) handles keys, double-click and pointer drags. It reports through `onDrag` (live), `onCommit` and `onReset`. `TaskDrawer` sets the panel's width with a CSS variable `--drawer-width`, bounded by CSS `min`/`max` from `md` up. During a drag `onDrag` writes the variable straight to the panel's DOM style, so the task does not re-render. The width goes to state and storage once, on release.

## Facts checked in the code
- `frontend/src/components/task/TaskDrawer.tsx`: the panel today is `<div className="card absolute inset-y-0 right-0 w-full max-w-4xl rounded-none border-y-0 border-r-0">` around `<TaskView …/>`. Its Escape listener is on `window`. `Hint` comes from `@/components/ui/Hint` (Radix `TooltipTrigger asChild`, so no extra wrapper element: the separator's parent is the panel).
- `frontend/src/lib/stored.ts`: `useStoredState<T>(key, initial, where): [T, (next: T) => void]`. It ignores a stored value of another type and writes JSON on each set.
- `.card` (globals.css `@utility card`) has no `overflow: hidden`, so a handle that sticks 6 px out of the panel is not clipped.
- Tokens: `bg-line`, `bg-cyan` and the `glow-box` utility exist (globals.css). The Tailwind v4 var syntax `w-(--x)` is already used (`AssigneePicker.tsx`). The global `prefers-reduced-motion` rule sets every `transition-duration` to 0.01ms, so no extra CSS is needed.
- Tests: Vitest + jsdom (`frontend/vitest.config.mts`, `css: false`, so `hidden md:flex` does not hide anything in tests). `vitest.setup.ts` runs `cleanup` after each test. The existing `src/components/task/__tests__/TaskDrawer.test.tsx` mocks `TaskView`. jsdom has no `setPointerCapture`, so the tests stub it.
- Playwright: `frontend/e2e/popups.spec.ts`, section `// 5. the task drawer …` on `/projects/POP/backlog?task=POP-1`. The viewport is 1600×900 (`playwright.config.ts`).
- Checks (AGENTS.md), from `frontend/`: `npx tsc --noEmit`, `npx eslint <changed files>`, `npm test` (or `npx vitest run <file>`). Do not run Prettier. Commit subjects look like `feat(tasks): …` and need a plain-sentence body. Each step is one commit. Do not change any version.

## File map
| File | Change | Responsibility |
|---|---|---|
| `frontend/src/components/task/drawerWidth.ts` | new | constants, `drawerMaxWidth`, `clampDrawerWidth`, `useDrawerWidth` |
| `frontend/src/components/task/__tests__/drawerWidth.test.ts` | new | clamp and hook tests |
| `frontend/src/components/task/DrawerResizeHandle.tsx` | new | the edge: ARIA, look, keys, double-click, pointer drag |
| `frontend/src/components/task/TaskDrawer.tsx` | modify | hook, panel width variable and CSS bounds, renders the handle |
| `frontend/src/components/task/__tests__/TaskDrawer.test.tsx` | modify | separator, keyboard, reset, drag tests |
| `frontend/e2e/popups.spec.ts` | modify | drag, then check the width after a reopen |

## Reference code

### A. `drawerWidth.ts`
```ts
"use client";

import { useStoredState } from "@/lib/stored";

export const DRAWER_WIDTH_KEY = "tasks.drawerWidth";
export const DRAWER_DEFAULT_WIDTH = 896; // max-w-4xl, the width before it could be resized
export const DRAWER_MIN_WIDTH = 720; // the task keeps its two columns
export const DRAWER_MARGIN = 48; // a strip of the page stays visible beside the drawer
export const DRAWER_STEP = 32; // one arrow key press

/** The widest the drawer may be in a window this wide; never under the narrowest. */
export function drawerMaxWidth(windowWidth: number): number {
  return Math.max(DRAWER_MIN_WIDTH, windowWidth - DRAWER_MARGIN);
}

/** A width within the drawer's range for this window, in whole pixels. */
export function clampDrawerWidth(width: number, windowWidth: number): number {
  const w = Number.isFinite(width) ? width : DRAWER_DEFAULT_WIDTH;
  return Math.round(Math.min(drawerMaxWidth(windowWidth), Math.max(DRAWER_MIN_WIDTH, w)));
}

/** The width the person chose, kept in this browser; clamped where it is used, so a smaller window squeezes it. */
export function useDrawerWidth(): [number, (width: number) => void] {
  return useStoredState(DRAWER_WIDTH_KEY, DRAWER_DEFAULT_WIDTH, "local");
}
```
`windowWidth` is always `window.innerWidth`. Like CSS `100vw`, it includes the scrollbar, so the script and the CSS agree.

### B. `DrawerResizeHandle.tsx` (final form, after step 3)
```tsx
"use client";

import { useRef, useState } from "react";

import { clampDrawerWidth, drawerMaxWidth, DRAWER_MIN_WIDTH, DRAWER_STEP } from "./drawerWidth";
import { Hint } from "@/components/ui/Hint";

type Drag = { x: number; start: number; last: number };

/** The drawer's left edge: drag, arrow keys, Home / End to resize, double-click to reset. Shown from md up. */
export function DrawerResizeHandle({
  width,
  onDrag,
  onCommit,
  onReset,
}: {
  width: number; // the chosen width, before clamping
  onDrag: (width: number) => void; // live, while dragging: show it without storing it
  onCommit: (width: number) => void;
  onReset: () => void;
}) {
  const drag = useRef<Drag | null>(null);
  const [dragging, setDragging] = useState(false);
  const now = clampDrawerWidth(width, window.innerWidth);

  const onKeyDown = (e: React.KeyboardEvent) => {
    const next = {
      ArrowLeft: now + DRAWER_STEP, // the edge is on the left: moving it left widens
      ArrowRight: now - DRAWER_STEP,
      Home: DRAWER_MIN_WIDTH,
      End: drawerMaxWidth(window.innerWidth),
    }[e.key];
    if (next === undefined) return; // Escape and the rest go on to the drawer
    e.preventDefault();
    onCommit(clampDrawerWidth(next, window.innerWidth));
  };

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault(); // no text selection while dragging
    // captured, the drag goes on over a mockup's iframe and outside the window
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, start: now, last: now };
    setDragging(true);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    d.last = clampDrawerWidth(d.start + d.x - e.clientX, window.innerWidth);
    onDrag(d.last);
  };
  const onPointerUp = () => {
    const d = drag.current;
    if (!d) return;
    drag.current = null;
    setDragging(false);
    if (d.last !== d.start) onCommit(d.last); // a plain click (or a double-click) stores nothing
  };
  // cut short (cancelled, capture lost): back to the committed width
  const onPointerCancel = () => {
    if (!drag.current) return;
    drag.current = null;
    setDragging(false);
    onDrag(width);
  };

  return (
    <Hint label="Drag to resize · double-click to reset">
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize task"
        aria-valuemin={DRAWER_MIN_WIDTH}
        aria-valuemax={drawerMaxWidth(window.innerWidth)}
        aria-valuenow={now}
        tabIndex={0}
        data-dragging={dragging || undefined}
        className="group absolute inset-y-0 -left-1.5 z-10 hidden w-3 cursor-col-resize touch-none items-center justify-center md:flex"
        onKeyDown={onKeyDown}
        onDoubleClick={onReset}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onLostPointerCapture={onPointerCancel}
      >
        <span
          aria-hidden
          className="absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 transition-colors group-hover:bg-cyan group-hover:glow-box group-focus-visible:bg-cyan group-focus-visible:glow-box group-data-dragging:bg-cyan group-data-dragging:glow-box"
        />
        <span
          aria-hidden
          className="relative h-8 w-1 rounded-full bg-line transition-[height,background-color] group-hover:h-14 group-hover:bg-cyan group-focus-visible:h-14 group-focus-visible:bg-cyan group-data-dragging:h-14 group-data-dragging:bg-cyan"
        />
      </div>
    </Hint>
  );
}
```
In step 2 the handle has everything except the four pointer handlers, the `drag` ref and the `dragging` state (`data-dragging` comes in step 3).

On pointer up the browser releases the capture by itself. The `lostpointercapture` event that follows finds `drag.current === null` and does nothing.

### C. `TaskDrawer.tsx` panel (after step 2)
```tsx
import { Maximize2, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, type CSSProperties } from "react";

import { DrawerResizeHandle } from "./DrawerResizeHandle";
import { DRAWER_DEFAULT_WIDTH, useDrawerWidth } from "./drawerWidth";
import { TaskView } from "./TaskView";
import { Hint } from "@/components/ui/Hint";
…
  const panel = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useDrawerWidth();
  // while dragging, only the panel's width changes: the task inside does not render again on every move
  const showWidth = useCallback((w: number) => panel.current?.style.setProperty("--drawer-width", `${w}px`), []);
…
      {/* from md up: the chosen width, kept between 720 px and the window less 48 px; full width on a phone */}
      <div
        ref={panel}
        style={{ "--drawer-width": `${width}px` } as CSSProperties}
        className="card absolute inset-y-0 right-0 w-full rounded-none border-y-0 border-r-0 md:w-(--drawer-width) md:min-w-[45rem] md:max-w-[calc(100vw-3rem)]"
      >
        <DrawerResizeHandle
          width={width}
          onDrag={showWidth}
          onCommit={setWidth}
          onReset={() => setWidth(DRAWER_DEFAULT_WIDTH)}
        />
        <TaskView …unchanged… />
      </div>
```
`--drawer-width` holds the chosen (stored) width, unclamped. CSS min/max clamp it. When the window is exactly 768 px wide, both limits are 720 px. `showWidth` returns `void` (wrap the body in braces if lint complains about the returned value).

### D. Test helpers for `TaskDrawer.test.tsx`
```tsx
import { beforeEach } from "vitest";
const KEY = "tasks.drawerWidth";
const stored = () => JSON.parse(localStorage.getItem(KEY) ?? "null");
const edge = () => screen.getByRole("separator", { name: "Resize task" });
const panel = () => edge().parentElement!;
const shown = () => panel().style.getPropertyValue("--drawer-width");
const open = () => render(<TaskDrawer taskKey="PAY-1" onClose={() => {}} onOpenTask={() => {}} />);

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("innerWidth", 1600); // widest: 1552
  // jsdom has no pointer capture
  Element.prototype.setPointerCapture ??= () => {};
  Element.prototype.releasePointerCapture ??= () => {};
  Element.prototype.hasPointerCapture ??= () => false;
});
afterEach(() => vi.unstubAllGlobals());
```
(Merge `afterEach` with the existing `afterEach(cleanup)`. Add `beforeEach` to the `vitest` import.)

## Steps

### 1. Drawer width module: constants, clamp and stored hook
See the step detail. Code: Reference A.

### 2. Resize handle with keyboard and double-click, wired into TaskDrawer
See the step detail. Code: Reference B (without the pointer parts), C and D.

### 3. Drag the edge with the pointer
See the step detail. Code: the pointer parts of Reference B.

### 4. Browser test: drag the drawer wider and keep it after reopening
See the step detail.

## Final verification
From `frontend/`:
- `npx tsc --noEmit`
- `npx eslint src/components/task/drawerWidth.ts src/components/task/DrawerResizeHandle.tsx src/components/task/TaskDrawer.tsx src/components/task/__tests__/drawerWidth.test.ts src/components/task/__tests__/TaskDrawer.test.tsx e2e/popups.spec.ts`
- `npm test`
- Browser tests on a fresh `megoo-e2e` stack, as AGENTS.md "Browser tests" shows (`npx playwright test --reporter=line`). `popups.spec.ts` must pass.
- By hand, at 1600 px: hover the edge (cyan with glow, the pill grows, `col-resize` cursor, the tooltip shows), drag, double-click (back to 896), Tab to the edge and press ←/→/Home/End, and Escape closes the drawer. Do the same on the board drawer. At 800 px the drawer is 720 to 752 px wide. Below 768 px there is no grip and the drawer is full width.
