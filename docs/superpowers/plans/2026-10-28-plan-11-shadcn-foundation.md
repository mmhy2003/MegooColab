# shadcn/ui Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring shadcn/ui (Radix) into the frontend under the Neon Grid look, rename the muted text colour to shadcn's name, and move the user menu, notification panel, icon-button hints, member picker, @mention list and assignee field onto it.

**Architecture:** shadcn components are copied into `frontend/src/components/shadcn/` and themed through shadcn's CSS variables, which point at the existing palette in `globals.css`. A small `PortalContainer` context lets Radix popups render inside the native modal `<dialog>` (which sits in the browser's top layer) instead of under it. Each migrated piece keeps its accessible names, so existing tests keep their meaning.

**Tech Stack:** Next 16, React 19, Tailwind 4, shadcn CLI (`radix` base), Radix UI, cmdk, Vitest + Testing Library (`@testing-library/user-event` for pointer and keyboard), Playwright.

**Spec:** `docs/superpowers/specs/2026-10-28-shadcn-foundation-design.md`

## Global Constraints

- **shadcn files live in `frontend/src/components/shadcn/`**, not `components/ui/`. *Plan ruling:* shadcn's `dialog.tsx`, `button.tsx`, `select.tsx`, `input.tsx`, `badge.tsx`, `avatar.tsx` would collide with the existing `Dialog.tsx`, `Button.tsx`, … on case-insensitive file systems (Windows, macOS), and `command` pulls in `dialog`. `components.json` aliases: `ui: "@/components/shadcn"`, `utils: "@/lib/utils"`.
- CLI: `npx shadcn@4.21.0` with `--base radix`; Tailwind 4 (no `tailwind.config.js`). Review every file the CLI writes; the CLI must not replace the Neon Grid CSS (restore anything it rewrites in `globals.css`).
- Dark mode is `data-theme="dark"` on `<html>`: keep `@custom-variant dark (&:where([data-theme=dark], [data-theme=dark] *));`, put dark values under `:root[data-theme="dark"]`, never a `.dark` class.
- Colours (spec table): `--background: var(--bg)`, `--foreground: var(--fg)`, `--card` and `--popover: var(--surface)` with `-foreground: var(--fg)`, `--secondary: var(--surface-2)` (`-foreground: var(--fg)`), `--border` and `--input: var(--line)`, `--primary: var(--cyan-ink)`, `--primary-foreground: var(--on-accent)`, `--ring: var(--cyan)`, `--accent: var(--surface-2)`, `--accent-foreground: var(--cyan-ink)`, `--destructive: var(--pink)`, `--muted: var(--surface-2)`, `--muted-foreground` = today's `--muted` values, `--radius: 0.25rem`.
- Neon Grid details on every shadcn piece: popup surfaces use `card` (surface, line border, shadow) and `glow-box`; focus shows the cyan outline from `:focus-visible`; highlighted items `bg-surface-2 text-cyan-ink`; font from the body (Geist). Tooltip: `bg-primary text-primary-foreground`, 12px, 4px corners.
- Popups that only show something (user menu, notifications) blur the page (`Backdrop`) and close on outside click and Escape. Field pickers (assignee, @mention) do not blur and close on outside click and Escape (owner's decision).
- Accessible names stay: `menu`/`menuitem`s of the user menu; `dialog` "Notifications"; buttons "Notifications", "Search (Ctrl+K)", "Role of …"; "Assignee"; "Mention someone"; "Search people".
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A Radix popup or tooltip opened inside the native modal `<dialog>` (the dialog's Close tooltip, the Members dialog): it shows above the dialog and can be clicked — Task 2 `test_portal_follows_the_dialog`, Task 7 browser check.
2. Escape in the assignee picker inside the task drawer closes only the picker; the drawer stays — Task 8 `escape closes only the picker`.
3. Light theme: tooltip and primary text readable (primary is `--cyan-ink`, not `--cyan`) — Task 2 `primary is the readable cyan`.
4. At 280px wide, the user menu, notification panel and pickers stay on screen (Radix collision padding) — Task 9 mobile check.
5. Keyboard only: Tab to the bell or the avatar, Enter opens, arrow keys move, Escape closes, focus returns to the trigger — Tasks 4 and 5 keyboard tests.

---

### Task 1: Rename the muted text colour to `muted-foreground`

**Files:**
- Modify: `frontend/src/app/globals.css`, `frontend/src/lib/useThemeColors.ts`, every `.tsx` using `text-muted` (298 uses, 108 files), `frontend/src/components/agents/AgentStatusDot.tsx` (`bg-muted`), tests asserting these classes
- Test: `frontend/src/lib/__tests__/themeTokens.test.ts`

**Interfaces:**
- Produces: CSS variable `--muted-foreground` (today's `--muted` values, both themes) and utility `text-muted-foreground`; `--muted` now `var(--surface-2)` (a background); `useThemeColors()` returns `muted` read from `--muted-foreground` (key name unchanged for the charts).

- [ ] **Step 1: Write the failing test** `themeTokens.test.ts`: read `globals.css` as text and assert `--muted-foreground: #6b5f99;` (light) and `--muted-foreground: #8f84c0;` (dark) exist, `--color-muted-foreground: var(--muted-foreground)` exists, and no `.tsx` under `src/` contains `/\btext-muted\b(?!-)/` (walk the tree with `fs`).
- [ ] **Step 2: Run it** — `npx vitest run src/lib/__tests__/themeTokens.test.ts`. Expected: FAIL (no `--muted-foreground`; hundreds of `text-muted`).
- [ ] **Step 3: Rename.** One mechanical pass: `text-muted` → `text-muted-foreground` where not already followed by `-`; in `globals.css` the token definitions and every `var(--muted)` read (`icon-btn`, the checkbox knob, …) become `--muted-foreground`, `--color-muted` becomes `--color-muted-foreground`, and a new `--muted: var(--surface-2)` + `--color-muted` is added; `useThemeColors` reads `--muted-foreground` for its `muted` key; `AgentStatusDot`'s grey dot becomes `bg-muted-foreground`; Badge's `"muted"` tone keeps its name with the renamed class. Nothing else changes in this commit.
- [ ] **Step 4: Run** the test, then `npx vitest run`, `npx tsc --noEmit`, `npm run lint`. Expected: all pass.
- [ ] **Step 5: Commit** `refactor(frontend): muted text colour is muted-foreground (shadcn's name)`.

### Task 2: shadcn setup, colours and the portal container

**Files:**
- Create: `frontend/components.json`, `frontend/src/lib/utils.ts` (`cn`), `frontend/src/components/shadcn/{tooltip,popover,dropdown-menu,command,dialog}.tsx` (from the CLI, then themed), `frontend/src/components/ui/PortalContainer.tsx`
- Modify: `frontend/package.json` (+ lock), `frontend/src/app/globals.css` (shadcn variables + `@theme inline` mappings), `frontend/src/components/ui/Dialog.tsx` (provides the container), `frontend/src/components/Providers.tsx` (`TooltipProvider`, delay 300ms)
- Test: `frontend/src/components/ui/__tests__/PortalContainer.test.tsx`, `frontend/src/lib/__tests__/themeTokens.test.ts` (extend)

**Interfaces:**
- Produces: `cn(...inputs: ClassValue[]): string`; `PortalContainerContext` and `usePortalContainer(): HTMLElement | null` (the open `<dialog>` element, else `null` = `<body>`); every shadcn `*Content` passes `container={usePortalContainer() ?? undefined}` to its Radix `Portal`; shadcn components `Tooltip`, `TooltipTrigger`, `TooltipContent`, `Popover`, `PopoverTrigger`, `PopoverAnchor`, `PopoverContent`, `DropdownMenu*`, `Command*`.

- [ ] **Step 1: Write the failing tests.** `PortalContainer.test.tsx`: render `<Dialog open title="T"><Popover open><PopoverTrigger>t</PopoverTrigger><PopoverContent aria-label="P">x</PopoverContent></Popover></Dialog>` and assert `screen.getByRole("dialog", { name: "P" })` is inside `screen.getByRole("dialog", { name: "T" })` (`test_portal_follows_the_dialog`); the same Popover outside a Dialog renders under `document.body`. Extend `themeTokens.test.ts`: `--primary: var(--cyan-ink)`, `--ring: var(--cyan)`, `--radius: 0.25rem`, `--background: var(--bg)`, and no `.dark {` selector in `globals.css` (`primary is the readable cyan`).
- [ ] **Step 2: Run them.** Expected: FAIL (modules and variables missing).
- [ ] **Step 3: Set up.** `npx shadcn@4.21.0 init --base radix` (answer: aliases above, CSS variables on) then `npx shadcn@4.21.0 add tooltip popover dropdown-menu command`; check `git diff src/app/globals.css` and keep only the variable mappings (Global Constraints values) and `@theme inline` entries; drop any `.dark {}` block and default OKLCH palette. Add `PortalContainer` (context + hook), wrap `Dialog`'s children in its provider with the `<dialog>` element, and pass `container` in each shadcn `*Content`. Theme each component per Global Constraints.
- [ ] **Step 4: Run** the tests, the full `npx vitest run`, tsc, lint. Expected: all pass (no visible change yet).
- [ ] **Step 5: Commit** `feat(frontend): shadcn/ui on the Neon Grid palette, portals inside dialogs`.

### Task 3: Tooltips on every icon-only button

**Files:**
- Create: `frontend/src/components/ui/Hint.tsx`
- Modify: every `icon-btn` button or link (the ~22 listed by `grep -rn 'icon-btn' src --include=*.tsx`: Header "Open menu", NotificationBell, ThemeToggle, DesktopSidebar toggle, TaskDrawer "Open full page" and "Close", TaskView "Delete task", Dialog "Close", CopyField, Snippet, FolderTree, ColumnEditor, LabelEditor, RepoEditor, Attachments, Links, admin users reset link, the search button); remove their `title`
- Test: `frontend/src/components/ui/__tests__/Hint.test.tsx`

**Interfaces:**
- Produces: `Hint({ label, children }: { label: string; children: React.ReactElement })` — Tooltip whose trigger is `children` (asChild) and whose content is `label`; the child keeps its own `aria-label`.

- [ ] **Step 1: Write the failing tests** (`user-event`): hovering a `<Hint label="Close"><button aria-label="Close" className="icon-btn"/></Hint>` shows `getByRole("tooltip", { name: "Close" })`; tabbing to it shows it too; Escape hides it; the button's accessible name stays "Close" and it has no `title`.
- [ ] **Step 2: Run.** Expected: FAIL (no `Hint`).
- [ ] **Step 3: Implement `Hint`** and wrap every icon-only button with it (label = its `aria-label`, or for the search button "Search (Ctrl+K)" / "Search (⌘K)"). Non-button `title` hints (task card icons, search filters) stay.
- [ ] **Step 4: Run** the full frontend suite, tsc, lint. Expected: pass (update any test that asserted a removed `title`, asserting the tooltip instead).
- [ ] **Step 5: Commit** `feat(frontend): tooltips on icon-only buttons`.

### Task 4: User menu as a DropdownMenu

**Files:**
- Modify: `frontend/src/components/shell/Header.tsx`
- Test: `frontend/src/components/shell/__tests__/Header.test.tsx`

- [ ] **Step 1: Write the failing tests** (`user-event`): clicking the name button opens `role="menu"` with menuitems Profile, Access tokens, My agents, Notifications, Sign out; ArrowDown moves focus between items and Enter on "Profile" navigates; Escape closes and focus returns to the name button; a click on `[data-backdrop]` closes it (existing test kept); the page behind is blurred while open (`[data-backdrop]` present).
- [ ] **Step 2: Run.** Expected: the keyboard tests FAIL (the hand-built menu has no arrow-key handling).
- [ ] **Step 3: Implement** with `DropdownMenu` (`modal={false}`; `onOpenChange` drives the `Backdrop`); items as `DropdownMenuItem asChild` around the existing `Link`s; drop the `onMouseLeave` close.
- [ ] **Step 4: Run** the shell tests and the full suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(frontend): user menu on Radix DropdownMenu`.

### Task 5: Notification panel as a Popover

**Files:**
- Modify: `frontend/src/components/notifications/NotificationBell.tsx`
- Test: `frontend/src/components/notifications/__tests__/Notifications.test.tsx`, `frontend/src/components/shell/__tests__/Header.test.tsx`

- [ ] **Step 1: Write the failing tests:** Enter on the focused bell opens `dialog` "Notifications"; Escape closes it and focus returns to the bell; Tab moves into the panel's links ("Mark all read", the notification, "See all"). Existing tests (unread count, mark read, outside click, Escape) stay.
- [ ] **Step 2: Run.** Expected: the focus-return test FAILS.
- [ ] **Step 3: Implement** with `Popover` (`PopoverContent aria-label="Notifications"`, `align="end"`, `collisionPadding={8}`), the `Backdrop` while open.
- [ ] **Step 4: Run** the tests and the full suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(frontend): notification panel on Radix Popover`.

### Task 6: Team member picker as an inline Command list

**Files:**
- Modify: `frontend/src/components/team/MemberPicker.tsx`
- Test: `frontend/src/components/team/__tests__/MemberPicker.test.tsx`

- [ ] **Step 1: Write the failing tests:** typing in "Search people" filters by name or email (existing); ArrowDown/ArrowUp move the highlighted person and Enter (or Space) ticks or unticks them; ticked people show as checked switches/boxes (`role="option"` with `aria-selected`); "Save members" saves exactly the ticked ids (existing); deactivated people show only if already members (existing).
- [ ] **Step 2: Run.** Expected: the keyboard tests FAIL.
- [ ] **Step 3: Implement** with `Command` (`shouldFilter={false}`, the existing filter kept), `CommandInput` labelled "Search people", one `CommandItem` per person (avatar, name, email, a check), inline in the dialog (no popover).
- [ ] **Step 4: Run** the tests and the full suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(frontend): member picker on cmdk, with keyboard`.

### Task 7: @mention list as Command in a Popover

**Files:**
- Modify: `frontend/src/components/task/CommentBox.tsx`
- Test: `frontend/src/components/task/__tests__/CommentBox.test.tsx`

- [ ] **Step 1: Write the failing tests:** typing `@an` in the comment box opens `listbox` "Mention someone" with matching people; focus stays in the comment box while ArrowDown/Enter pick (existing behaviour); a click outside closes the list; there is no `[data-backdrop]` (no blur); inside the task drawer, Escape closes the list and not the drawer.
- [ ] **Step 2: Run.** Expected: the outside-click and Escape-in-drawer tests FAIL.
- [ ] **Step 3: Implement** with `Popover` (`open` driven by the mention state, `PopoverAnchor` around the textarea, `onOpenAutoFocus` prevented so the cursor stays) and `Command` with its value driven by the existing keyboard handling; Escape handled with `stopPropagation` so the drawer's window listener does not see it.
- [ ] **Step 4: Run** the tests and the full suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(frontend): @mention list on Radix Popover and cmdk`.

### Task 8: Searchable assignee field

**Files:**
- Create: `frontend/src/components/task/AssigneePicker.tsx`
- Modify: `frontend/src/components/task/TaskFields.tsx`, `frontend/e2e/helpers/` (new `pickAssignee(scope: Locator, name: string)`), `frontend/e2e/{agents,notifications,workflow}.spec.ts` (use it instead of `selectOption`)
- Test: `frontend/src/components/task/__tests__/TaskFields.test.tsx`

**Interfaces:**
- Produces: `AssigneePicker({ users, agents, task, disabled, onPatch })` — a button labelled "Assignee" showing the current assignee's name (or "Unassigned"), opening a Popover with a Command: groups "People" and "Agents", "Unassigned" first, agents the user cannot use shown disabled with `AGENT_DENIED` as their hint, deactivated people hidden unless assigned.

- [ ] **Step 1: Write the failing tests** (rewrite the `pick` helper to open the picker and choose by name): choosing a person patches `assignee_user_id`; an agent patches `assignee_agent_id`; "Unassigned" clears both; typing filters; an unusable agent cannot be chosen; the button's name is "Assignee" and it shows "Ann's Codex" for an agent assignee; there is no `[data-backdrop]`; `escape closes only the picker` inside a rendered `TaskDrawer`.
- [ ] **Step 2: Run.** Expected: FAIL (still a native select).
- [ ] **Step 3: Implement `AssigneePicker`** and use it in `TaskFields`; add `pickAssignee` to the e2e helpers and use it in the three specs.
- [ ] **Step 4: Run** the tests and the full suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(frontend): searchable assignee picker`.

### Task 9: Browser verification

**Files:**
- Modify: `frontend/e2e/popups.spec.ts` (keyboard on the menu and notifications, a tooltip on focus), `frontend/e2e/mobile.spec.ts` (open the user menu, the notification panel and the assignee picker at 280px and check each stays within the screen)

- [ ] **Step 1: Add the checks** above.
- [ ] **Step 2: Run on a fresh stack** (`down -v`, `up -d --build --wait`, `npx playwright test`). Expected: all pass. Tear down.
- [ ] **Step 3: Screenshots** in both themes of the user menu, the notification panel, the assignee picker, a tooltip and the Members dialog, compared by eye with the Neon Grid look.
- [ ] **Step 4: Commit** `test(e2e): shadcn pieces by keyboard and on a phone`.
