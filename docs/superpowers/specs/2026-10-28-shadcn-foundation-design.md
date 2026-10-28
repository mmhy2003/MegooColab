# shadcn/ui foundation — design

Date: 2026-10-28. Status: proposed; the owner asked for this plan ("yes" to adopting shadcn gradually).

## Why

MegooColab's frontend has its own small set of UI pieces (`frontend/src/components/ui/`: Button, Input, Select, Dialog,
Badge, Avatar, Backdrop, CopyField, Markdown, PageHeader), styled with Tailwind 4 and the Neon Grid colours. The
interactive ones are hand-built, and their behaviour has needed fixing by hand: clicks outside popups, focus when a
popup opens, keyboard use. shadcn/ui gives the same kind of components with that behaviour built in (Radix
underneath: focus, keyboard, outside clicks, screen readers), as source code copied into the project, so they can wear
MegooColab's look exactly.

The owner wants shadcn to respect MegooColab's style and colour palette, and to adopt it gradually: first the pieces
that need the behaviour most, the rest later as they are touched.

## Goals

1. shadcn set up in the frontend (Tailwind 4, the `cn` helper, `components.json`), its components in
   `frontend/src/components/ui/` beside the existing ones.
2. One colour system: shadcn's variable names mapped onto the Neon Grid palette, in both themes, with the existing
   `data-theme` light/dark switch (no `.dark` class).
3. These pieces moved onto shadcn (Radix) components:
   - the user menu in the header → **DropdownMenu**;
   - the notification panel → **Popover**;
   - every icon-only button (`icon-btn`, about 20: Close, Notifications, Open menu, Open full page, theme, sidebar
     collapse, …) → a **Tooltip** showing its existing accessible name, on hover and on keyboard focus; its `title`
     goes. *My call:* all of them, not only the four that have a `title` today. Hover hints on things that are not
     buttons (task card icons, search filters) keep their `title`;
   - the team member picker (`components/team/MemberPicker.tsx`) → an inline **Command** list inside the "Members of …"
     dialog: still a searchable list where several people are ticked and saved with "Save members", now moved
     through with the arrow keys. *My call:* inline, not a popover (it is not a popup today, and a Radix popover would
     open under the native modal dialog);
   - the comment @mention picker (`components/task/CommentBox.tsx`) → **Command** in a **Popover** anchored to the
     comment box, the cursor staying in the box;
   - the task assignee field → a searchable **Combobox** (Command in a Popover), since a list of people and agents
     grows long.
4. Every shadcn component brought in wears the Neon Grid details: the cyan focus ring and glow (`glow-box`,
   `glow-cyan`), the 4px corners, uppercase display buttons where today's buttons are, both themes.
5. Behaviour stays as decided earlier: popups that only show something (the user menu, the notification panel) close
   on an outside click and Escape, with the page behind blurred (`Backdrop` rules from the popups work); the sticky
   header and collapsible sidebar keep working; everything fits a 280px screen.
6. Pickers attached to a field (the assignee combobox, the @mention list) behave like a normal dropdown (owner's
   decision): no blur, so what is being typed stays sharp, and a click outside or Escape closes the list. Nothing is
   lost: the text typed in them is only a search.

## Non-goals

- Replacing every component now. Button, Input, Badge, Avatar, PageHeader, Markdown, CopyField and **Dialog** stay as
  they are; each moves to shadcn later only when that code is being changed anyway.
- Changing the look. A person using MegooColab should not see a different design, only steadier behaviour.
- Plain form dropdowns (`<select>`, e.g. task type, priority, column category): they stay native, because phones show
  their own, better picker for them. *My call.*
- New features.

## Anti-goals

- Two colour systems side by side, where the same name means different things (see "Muted").
- A component that looks shadcn-default (grey, rounded, no glow) next to Neon Grid ones.
- Breaking the existing tests' expectations of roles and names (menu, menuitem, dialog "Notifications",
  "Search (Ctrl+K)", "Role of …", etc.), which reflect real accessibility.

## Colours

shadcn's variables, pointed at the existing palette (`frontend/src/app/globals.css`), in `:root` / light and
`:root[data-theme="dark"]`:

| shadcn variable | Neon Grid |
|---|---|
| `--background` / `--foreground` | `--bg` / `--fg` |
| `--card`, `--popover` (+ `-foreground`) | `--surface` / `--fg` |
| `--secondary` | `--surface-2` |
| `--border`, `--input` | `--line` |
| `--primary` (+ `-foreground`) | `--cyan-ink` / `--on-accent` (*my call:* the darker cyan in the light theme, as today's buttons use; `--cyan` with white text fails AA; in the dark theme `--cyan-ink` is `--cyan`) |
| `--ring` | `--cyan` |
| `--accent` (+ `-foreground`) | `--surface-2` / `--cyan-ink` (shadcn uses "accent" for hovered items) |
| `--destructive` | `--pink` |
| `--radius` | `0.25rem` (today's 4px) |

### Muted

The one clash: in MegooColab `--muted` is the grey **text** colour (`text-muted`, 298 uses in 108 files); in shadcn
`--muted` is a **background** and grey text is `--muted-foreground`. *My call:* adopt shadcn's meaning. Rename the text
colour to `--muted-foreground` and every `text-muted` to `text-muted-foreground` (a mechanical, whole-codebase rename
in one commit), and give `--muted` shadcn's meaning (`--surface-2`). The one existing `bg-muted`/`border-muted` use is
checked by hand.

## Constraints

- Next 16, React 19, Tailwind 4 (no `tailwind.config.js`), TanStack Query, Vitest + Testing Library, Playwright.
- Dark mode is `data-theme="dark"` on `<html>` (`@custom-variant dark` already defined); shadcn's CSS is adapted to it.
- The shadcn CLI may be used to add components; whatever it writes is reviewed and adjusted to the palette.
- Dependencies stay to what shadcn needs (Radix packages per component, `class-variance-authority`, `clsx`,
  `tailwind-merge`, `cmdk` for Command, `tw-animate-css` if its animations are used).

## Proof

- Every existing frontend unit test and browser test keeps passing (adjusted only where a test reached into markup
  that changed, never to weaken what it checks).
- New tests for each migrated piece: keyboard use (arrow keys and Enter in the menu and pickers, Escape closes),
  outside click closes, the tooltip shows on focus.
- The browser tests at 280px and the popups test pass; screenshots of the header menu, notifications, assignee
  picker and a tooltip in both themes show the Neon Grid look.

## Notes for the builder (found by the builder check)

- `lib/useThemeColors.ts` reads `--muted` by name for charts: the rename covers it, and so do the checkbox knob and
  `.icon-btn` in `globals.css`, Badge's `"muted"` tone and `AgentStatusDot`'s `bg-muted`.
- The task drawer closes on Escape from a window listener: Escape inside a picker must close only the picker.
- Popup content portalled to `<body>` sits above the sticky header (`z-30`).

## Left to the builder

- Which shadcn components to pull for each piece and how to wrap them (e.g. a small `AssigneePicker`).
- The exact class changes that give each component the Neon Grid details.
- Whether the muted rename is a codemod script or a careful search-and-replace, as long as it lands in one commit
  and nothing else changes in it.
- Order of the migrations.
