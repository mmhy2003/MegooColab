# MC-18 plan: the Search list follows the selected result

## Goal
In the Ctrl+K Search popup, ↓/↑ keep the selected result fully in view. Group headings stay pinned while the list scrolls, and the selected row gets a cyan bar and tint.

## Architecture
All changes are in `frontend/src/components/search/SearchBox.tsx`. The key handler selects the next index and calls `scrollIntoView?.({ block: "nearest" })` on that option, which it finds by a stable id (`quick-search-option-<i>`). The same id feeds `aria-activedescendant`. CSS scroll margins (`scroll-mt-6` on every option, `scroll-mb-11` on the last one) leave room for the sticky heading and the "See all" link. The mouse selects a row on `onMouseMove`, and only when the pointer position changed since the last event (a ref holds it). Typing a new search resets the listbox's `scrollTop` to 0 through a ref. No new files, no dependency changes, no backend changes.

## File map
| File | Change |
|---|---|
| `frontend/src/components/search/SearchBox.tsx` | option ids and `aria-activedescendant`; keyboard scroll; scroll reset; mouse-move selection; sticky headings, highlight, scroll margins |
| `frontend/src/components/search/__tests__/SearchBox.test.tsx` | new Vitest cases (below) |
| `frontend/e2e/search.spec.ts` | step 5 of the existing test: short viewport, ↓ to the last result and ↑ back, each selected row fully in the viewport |
| `README.md` | the "Global search end-to-end test" paragraph mentions the new step |

Repo rules (AGENTS.md): write the test first and watch it fail; checks are `cd frontend && npx tsc --noEmit`, `npx eslint <changed files>`, `npm test`; don't run Prettier. Commit subjects follow `type(area): what changed`, with a body that explains why, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Work on the current branch `megoo/MC-18-fix-search`.

Run a single Vitest file with: `cd frontend && npx vitest run src/components/search/__tests__/SearchBox.test.tsx`.

---

## Step 1. Option ids and aria-activedescendant on the search field

**Test first.** Add this to the `describe("SearchLauncher")` block in `SearchBox.test.tsx`:

```tsx
it("the search field names the selected result for screen readers", async () => {
  setup();
  const box = open();
  expect(box).not.toHaveAttribute("aria-activedescendant");
  fireEvent.change(box, { target: { value: "retry" } });
  await screen.findByRole("listbox");
  const options = screen.getAllByRole("option");
  expect(options[0].id).toBe("quick-search-option-0");
  expect(box).toHaveAttribute("aria-activedescendant", "quick-search-option-0");
  fireEvent.keyDown(box, { key: "ArrowDown" });
  expect(box).toHaveAttribute("aria-activedescendant", options[1].id);
  fireEvent.click(screen.getByRole("option", { name: /Ann Lee/ }));
  expect(box).not.toHaveAttribute("aria-activedescendant");
});
```
Run the file. It should fail because the option has no id and the attribute is missing.

**Implementation** in `SearchBox.tsx`:
```ts
// module level, next to UNAVAILABLE
const optionId = (i: number) => `quick-search-option-${i}`;
```
- On the combobox `<input>`: `aria-activedescendant={!card && flat[active] ? optionId(active) : undefined}`
- On each option `<div role="option">`: `id={optionId(mine)}`

Run the file again: everything passes. Then run tsc, eslint on both files, and `npm test`.

Commit: `fix(search): the search field names the selected result for screen readers (MC-18)`

---

## Step 2. ↓/↑ scroll the selected result into view; a new search goes back to the top

**Tests first:**
```tsx
it("arrow keys scroll the selected result into view, the least needed", async () => {
  const scroll = vi.fn();
  Element.prototype.scrollIntoView = scroll;
  try {
    setup();
    const box = open();
    fireEvent.change(box, { target: { value: "retry" } });
    await screen.findByRole("listbox");
    const options = screen.getAllByRole("option");
    scroll.mockClear();
    fireEvent.keyDown(box, { key: "ArrowDown" });
    fireEvent.keyDown(box, { key: "ArrowDown" });
    expect(scroll).toHaveBeenLastCalledWith({ block: "nearest" });
    expect(scroll.mock.contexts.at(-1)).toBe(options[2]);
    fireEvent.keyDown(box, { key: "ArrowUp" });
    expect(scroll).toHaveBeenCalledTimes(3);
    expect(scroll).toHaveBeenLastCalledWith({ block: "nearest" });
    expect(scroll.mock.contexts.at(-1)).toBe(options[1]);
  } finally {
    Reflect.deleteProperty(Element.prototype, "scrollIntoView");
  }
});

it("a new search goes back to the top of the list", async () => {
  setup();
  const box = open();
  fireEvent.change(box, { target: { value: "retry" } });
  const list = await screen.findByRole("listbox");
  // jsdom does no layout: give the list a scroll position of its own
  Object.defineProperty(list, "scrollTop", { value: 120, writable: true, configurable: true });
  fireEvent.change(box, { target: { value: "retry p" } });
  expect(list.scrollTop).toBe(0);
  expect(screen.getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
});
```
Both should fail: `scrollIntoView` is never called, and `scrollTop` stays at 120.

**Implementation:**
```ts
import { useEffect, useRef, useState } from "react";
...
const listRef = useRef<HTMLDivElement>(null);

// only the keyboard scrolls, and only as far as needed to show the row whole; no animation, so a held key keeps up
const select = (i: number) => {
  setActive(i);
  document.getElementById(optionId(i))?.scrollIntoView?.({ block: "nearest" });
};
```
- `ArrowDown`: `select(Math.min(active + 1, flat.length - 1));`
- `ArrowUp`: `select(Math.max(active - 1, 0));`
- In the input's `onChange`, after `setCard(null)`: `if (listRef.current) listRef.current.scrollTop = 0;`
- On the listbox div: `ref={listRef}`

Hover does not go through `select`. The existing tests keep passing. Run the file, then tsc, eslint and `npm test`.

Commit: `fix(search): arrow keys keep the selected result in view, and a new search starts at the top (MC-18)`

---

## Step 3. The mouse selects a row only when it really moves

**Tests first:**
```tsx
it("moving the mouse onto a row selects it, without scrolling", async () => {
  const scroll = vi.fn();
  Element.prototype.scrollIntoView = scroll;
  try {
    setup();
    fireEvent.change(open(), { target: { value: "retry" } });
    await screen.findByRole("listbox");
    const options = screen.getAllByRole("option");
    scroll.mockClear();
    fireEvent.mouseMove(options[2], { clientX: 40, clientY: 100 });
    fireEvent.mouseMove(options[2], { clientX: 42, clientY: 101 });
    expect(options[2]).toHaveAttribute("aria-selected", "true");
    expect(scroll).not.toHaveBeenCalled();
  } finally {
    Reflect.deleteProperty(Element.prototype, "scrollIntoView");
  }
});

it("a row that slides under a resting mouse does not take the selection", async () => {
  setup();
  const box = open();
  fireEvent.change(box, { target: { value: "retry" } });
  await screen.findByRole("listbox");
  const options = screen.getAllByRole("option");
  fireEvent.mouseMove(options[0], { clientX: 40, clientY: 100 });
  fireEvent.keyDown(box, { key: "ArrowDown" });
  fireEvent.keyDown(box, { key: "ArrowDown" });
  // the list scrolled: the browser reports the row now under the pointer, at the same position
  fireEvent.mouseMove(options[1], { clientX: 40, clientY: 100 });
  expect(options[2]).toHaveAttribute("aria-selected", "true");
  fireEvent.mouseMove(options[1], { clientX: 40, clientY: 104 });
  expect(options[1]).toHaveAttribute("aria-selected", "true");
});
```
Both should fail today: `onMouseEnter` doesn't fire on `mousemove`, so the selection never moves.

**Implementation:**
```ts
// the pointer's last position: rows that slide under a resting pointer while the list scrolls must not take the selection
const pointer = useRef<{ x: number; y: number } | null>(null);
const onMouseMove = (e: React.MouseEvent, i: number) => {
  const last = pointer.current;
  pointer.current = { x: e.clientX, y: e.clientY };
  if (last && (last.x !== e.clientX || last.y !== e.clientY)) setActive(i);
};
```
On the option, replace `onMouseEnter={() => setActive(mine)}` with `onMouseMove={(e) => onMouseMove(e, mine)}`. `onClick` stays as it is. Run the file, then tsc, eslint and `npm test`.

Commit: `fix(search): a resting mouse no longer takes the selection back while the list scrolls (MC-18)`

---

## Step 4. Pinned group headings, a clearer selected row, scroll margins

**Test first:**
```tsx
it("pins the group headings and marks the selected row clearly", async () => {
  setup();
  fireEvent.change(open(), { target: { value: "retry" } });
  const list = await screen.findByRole("listbox");
  for (const h of within(list).getAllByRole("heading")) expect(h).toHaveClass("sticky", "top-0", "z-10", "bg-surface");
  const options = screen.getAllByRole("option");
  for (const o of options) expect(o).toHaveClass("scroll-mt-6");
  expect(options.at(-1)).toHaveClass("scroll-mb-11");
  expect(options[0]).not.toHaveClass("scroll-mb-11");
  expect(options[0]).toHaveClass("bg-cyan/15", "shadow-[inset_3px_0_0_var(--cyan)]");
  expect(options[0]).not.toHaveClass("bg-surface-2");
  expect(options[1]).not.toHaveClass("bg-cyan/15");
});
```
This should fail: the classes are missing.

**Implementation:**
- `h3` className: `"sticky top-0 z-10 bg-surface pb-1 text-[11px] tracking-widest text-muted-foreground uppercase"`. The `bg-surface` is the dialog's own background, so rows pass under the heading. Its sticky parent is the group div, so it is pinned only while its group is on screen.
- Option className:
```ts
className={`cursor-pointer scroll-mt-6 rounded px-2 py-1 text-sm ${mine === flat.length - 1 ? "scroll-mb-11" : ""} ${
  mine === active ? "bg-cyan/15 shadow-[inset_3px_0_0_var(--cyan)]" : ""
}`}
```
`scroll-mt-6` (24px) clears the pinned heading, which is about 20px tall. `scroll-mb-11` (44px) brings the "See all N results" link (about 36px with its gap) into view. Matched words (`<mark>`, `bg-cyan/25`) stay visible on the tint. Run the file, then tsc, eslint and `npm test`. If you can, open the dev app and check the look in both themes.

Commit: `feat(search): group headings stay pinned and the selected row stands out (MC-18)`

---

## Step 5. Browser test: in a short window the selected result stays fully in view

Add this at the end of the `test("search finds what you may open")` body in `frontend/e2e/search.spec.ts`, after step 4. It reuses `request` (admin), `page` (Bea), `box` and `post`:

```ts
  // 5. in a short window the list follows ↓ and ↑: the selected result is always fully in view
  for (let i = 1; i <= 5; i++) await post(request, "/api/projects/SRA/tasks", { title: `Scrolling check ${i}`, type: "task" });
  await page.setViewportSize({ width: 1280, height: 300 });
  await page.goto("/projects");
  await expect
    .poll(
      async () => {
        if (!(await box.isVisible())) await page.keyboard.press("Control+K");
        await box.fill("");
        await box.fill("scrolling check");
        return page.getByRole("option", { name: /Scrolling check 5/ }).waitFor({ state: "visible", timeout: 3_000 }).then(() => true, () => false);
      },
      { timeout: 30_000 },
    )
    .toBe(true);
  const options = page.getByRole("option");
  const n = await options.count();
  expect(n).toBeGreaterThanOrEqual(5);
  await expect(options.first()).toBeInViewport({ ratio: 1 });
  for (let i = 1; i < n; i++) {
    await box.press("ArrowDown");
    await expect(options.nth(i)).toHaveAttribute("aria-selected", "true");
    await expect(options.nth(i)).toBeInViewport({ ratio: 1 });
  }
  await expect(page.getByRole("link", { name: /See all \d+ results/ })).toBeInViewport();
  for (let i = n - 2; i >= 0; i--) {
    await box.press("ArrowUp");
    await expect(options.nth(i)).toHaveAttribute("aria-selected", "true");
    await expect(options.nth(i)).toBeInViewport({ ratio: 1 });
  }
```
At 300px the dialog (max 90vh) and the list (max 60vh) both overflow with 5 rows plus a heading and the link. Without the fix, the 5th row sits below the viewport. Also:
- Add to the file's header comment: "in a short window, ↓ and ↑ keep the selected result fully in view".
- Add a matching sentence to the "Global search end-to-end test" paragraph in `README.md`: in a short window, Bea presses ↓ to the last "Scrolling check" result and ↑ back, and each selected result is fully in view.

Run it on a freshly built stack as AGENTS.md "Browser tests" describes (`megoo-e2e` project, stop and restart `megoocolab-dev-caddy-1`), then `cd frontend && npx playwright test e2e/search.spec.ts`. If Docker or the stack isn't available, say so in the report instead of claiming the test passed. Run tsc and eslint on the spec.

Commit: `test(search): the selected result stays in view in a short window (MC-18)`

---

## Final verification
```bash
cd frontend
npx tsc --noEmit
npx eslint src/components/search/SearchBox.tsx src/components/search/__tests__/SearchBox.test.tsx e2e/search.spec.ts
npm test
npx playwright test e2e/search.spec.ts   # on a fresh megoo-e2e stack
```
Manual check in the dev app: Ctrl+K, type a common word, hold ↓. The list follows the selection, headings stay pinned, the selected row has the cyan bar, a resting mouse doesn't steal the selection, and typing again goes back to the top.
