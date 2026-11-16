# MC-18 design: the Search list follows the selected result

## Goal
In the Search popup (Ctrl+K), pressing ↓ or ↑ keeps the selected result in view: the list scrolls with the selection, so the mouse is never needed to see what is selected. The group headings stay pinned while the list scrolls, and the selected row stands out more. Mockup v2 shows it ("New"), next to today's behaviour ("Today").

## Decisions
- **Cause.** `SearchBox` (`frontend/src/components/search/SearchBox.tsx`) changes the selected index on ↓/↑, but nothing scrolls the list (`max-h-[60vh] overflow-auto`). A quick search returns up to 35 results (`QUICK_PER_KIND = 5` for each of 7 kinds), which is taller than the list. The scrollbar is also hidden until the pointer is over the list, so nothing shows where the selection went.
- **The human chose "The fix + both extras"**, over the fix alone, the fix with pinned headings only, and the fix with the clearer row only. So this design has three parts:
  1. the list follows the selection;
  2. group headings (Tasks, Documents, …) stay pinned at the top of the list while it scrolls;
  3. the selected row gets a cyan bar and tint.
- **Scroll the least needed, with no animation.** The list moves only when the selected row would be cut off, and only far enough to show it whole (`scrollIntoView({ block: "nearest" })`, as `FolderTree` and `EntitySidebar` already do). Rejected: centring the selected row (the list would jump on every key press) and smooth scrolling (it falls behind when the key is held down).
- **Only the keyboard scrolls the list.** Selecting a row with the mouse does not scroll: a half-visible row must not jump under the pointer.
- **The mouse selects a row only when it really moves.** Today a row is selected when the pointer enters it (`onMouseEnter`). Once the list scrolls by itself, rows slide under a resting pointer, and the browser reports that as entering them: the mouse would take the selection back on every key press. So a row is selected by the mouse only when the pointer's position differs from the last one seen; the first position seen is only recorded. Rejected: keeping `onMouseEnter`, and switching the mouse off while keys are used (more state, same result).
- **A new search starts at the top.** Typing already selects the first result; the list now also scrolls back to the top.
- **Screen readers hear the selected result.** The search field names the selected option with `aria-activedescendant`. This is the same bug for people who do not see the screen, it is two attributes, and it changes nothing visible.
- **No change to which keys do what.** ↓ and ↑ still stop at the last and first result (no wrap-around), and Home, End, Page Up and Page Down keep their normal meaning in the text field.

## Architecture
Everything is in `frontend/src/components/search/SearchBox.tsx`. No new component, no new dependency, no backend change.

- **Following the selection.** The key handler works out the next index, selects it and scrolls that option into view with `block: "nearest"`. The option elements already exist when the key is pressed (only their selected state changes, never their size), so the handler can call it directly on the listbox's option with that index; no effect is needed, and hover never goes through this path. The call is optional (`scrollIntoView?.(…)`), as elsewhere in the repo, because jsdom has no `scrollIntoView`.
- **Room for the pinned heading and the last link**, with CSS scroll margins, so one `scrollIntoView` call is enough:
  - every option has a top scroll margin of the heading's height (`scroll-mt-6`), so going up never leaves the selected row under the pinned heading;
  - the last option has a bottom scroll margin (`scroll-mb-11`), so on the last result the "See all N results" link is in view too.
- **Pinned headings.** Each group's `h3` becomes `sticky top-0 z-10 bg-surface pb-1` (the dialog's own background, so rows pass under it). It is pinned only while its group is on screen; the next group's heading replaces it.
- **Selected row.** `bg-surface-2` becomes `bg-cyan/15 shadow-[inset_3px_0_0_var(--cyan)]`: the same idea as the selected chat in `ChatList` (`shadow-[inset_2px_0_0_var(--cyan)]`), a little stronger. It works in both themes because it uses the theme's `--cyan`. Matched words (`<mark>`, `bg-cyan/25`) stay visible on it.
- **Mouse.** `onMouseEnter` on the option is replaced by `onMouseMove`, with the pointer's last position kept in a ref (compared by `clientX`/`clientY`); it selects only when the position changed. Clicking a row works as before.
- **New search.** The field's `onChange` also sets the listbox's `scrollTop` to 0 (through a ref on the listbox).
- **`aria-activedescendant`.** Each option gets an id (for example `quick-search-option-<index>`), and the combobox points at the selected one while results are shown; the attribute is absent when there are no results or a person/agent card is open.

## Data and interfaces
None. The API, the `Hit` type and `useQuickSearch` are unchanged.

## Error handling and edge cases
- **Few results (the list does not scroll):** `scrollIntoView` with `nearest` does nothing; pinned headings look like today's headings.
- **First and last result:** ↑ on the first result brings the list fully to the top; ↓ on the last shows the "See all" link.
- **Short windows**, where the dialog itself also scrolls (`max-h-[90vh] overflow-auto`): `scrollIntoView` scrolls both the list and the dialog as far as needed.
- **Results that change under the selection** (`keepPreviousData` shows the old list until the new one arrives): the selection is already reset to the first result when the text changes, and the list is at the top.
- **A person or agent card is open:** the list is not rendered; arrow keys change nothing visible, as today.
- **Reduced motion:** nothing animates, so nothing to switch off.

## Testing
Test first, as the repo requires: each test below fails on today's code.

- **Vitest, `frontend/src/components/search/__tests__/SearchBox.test.tsx`** (stubbing `Element.prototype.scrollIntoView` as `FolderTree.test.tsx` does):
  - ↓ scrolls the newly selected option into view with `{ block: "nearest" }`, and ↑ does the same for the one above;
  - moving the mouse onto a row selects it without calling `scrollIntoView`;
  - a mouse event at the same position as the last one (the list scrolled under a resting pointer) does not change the selection; one at a new position does;
  - typing a new search puts the list's `scrollTop` back to 0;
  - the combobox's `aria-activedescendant` is the id of the selected option, and follows ↓;
  - the selected option carries the new highlight classes, the headings are sticky, and the options carry the scroll margins.
  - The existing tests (arrow keys and Enter, cards, snippets as text) keep passing.
- **Playwright, one step added to `frontend/e2e/search.spec.ts`**, because jsdom does no layout and cannot show that the row is really visible: in a short viewport, with enough results to overflow the list, press ↓ to the last result and check that the selected option is fully in the viewport after each press (`toBeInViewport({ ratio: 1 })`), then ↑ back to the first.
- **Checks:** `npx tsc --noEmit`, `npx eslint` on the changed files, `npm test`.

## Out of scope
- Wrap-around from the last result to the first, and Home, End, Page Up and Page Down in the list.
- The full results page (`/search`) and the Knowledge Base search page: they have no keyboard selection.
- The number of quick results per kind, and anything in the backend.
- Showing the scrollbar all the time (the app hides scrollbars until the pointer is over them, everywhere).