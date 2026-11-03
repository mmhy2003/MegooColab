# Mobile-friendly MegooColab (narrow phones down to 280 px)

Status: approved layouts (chat, task page, dashboard), written up for planning. The approved mockups are in
`.superpowers/brainstorm/1996-1793694540/content/` (`chat-phone.html`, `other-pages.html`; git-ignored).

## Why

The owner uses MegooColab on a Samsung Galaxy Fold. On its cover screen, the Chats page runs past the right edge and
the whole page scrolls sideways. A layout audit of every page (280 and 344 CSS px, touch phone emulation, data with
long words, links, code and tables) found the cause and a set of smaller problems elsewhere. The goal is an app that
works on the narrowest phone in use without zooming or sideways scrolling, and that gives the content (a
conversation, a task) most of the screen.

## Goals

- **No page scrolls sideways at 280 px or wider.** This covers every page, popup and dialog, signed in or out, with
  real-world content: long URLs, long file paths, long identifiers in inline code, long project/team/agent names,
  long titles, and long dropdown options.
- **Wide content scrolls inside its own box and shows that it does.** That means code blocks, Markdown tables, data
  tables and command boxes. A box that scrolls sideways shows a fade (and, for tab bars, a ›) at the edge that has
  more.
- **The content gets the screen on phones.** An open chat and an open task are readable and writable on a
  280 × 650 screen.
- **Nothing changes at md (768 px) and up**, unless a fix is width-independent (a long word wrapping, a dropdown not
  stretching its container). Desktop layouts stay as they are.

## Non-goals

- A native app, a separate mobile site, or a new navigation model. The existing shell (top bar, ☰ main menu) stays.
- Landscape-specific or tablet-specific layouts beyond what the fixes give for free.
- Redesigning desktop pages.
- These bugs, found during the audit, are not mobile problems and are handled separately:
  - A question's body (`/questions/:id`) shows raw Markdown (code fences, pipe tables).
  - The dashboard's "Workflows by stage" shows a full "Done" bar for a count of 0.

## Anti-goals

- Hiding content or actions on phones to make things fit. Everything reachable on desktop stays reachable on a phone,
  even if behind a tap ("Filters", the comment bar).
- Breaking long words mid-word where a normal wrap would do. Wrap anywhere only as the fallback for an unbreakable
  string (`overflow-wrap: anywhere` semantics), never `word-break: break-all` on prose.
- Text so small it needs zooming (nothing under 11 px), or tap targets under 32 px in either dimension.

## Constraints

- Next.js app in `frontend/`, Tailwind, existing components. No Prettier. Copy follows the app's existing plain style.
- Breakpoints: the app's phone layouts are below `md`. The narrowest supported width is 280 px; 344 px (the newer
  Fold cover screen) and 360–430 px phones must look right too.
- The existing e2e check `frontend/e2e/mobile.spec.ts` ("every page fits a 280-pixel screen") is the guard. It
  missed this problem because it never visited the Chats pages or any dialog, and its overflow test treats anything
  inside a box with `overflow-x` other than `visible` as fine (a `overflow-y: auto` scroller computes to
  `overflow-x: auto`, which hid the chat thread). It must be extended (see Testing).

## The cause (from the audit)

1. **Grids and flex rows without a minimum-width floor.** On phones the Chats page grid has no explicit column, so
   its single implicit column sizes to the widest unbreakable content. One long URL or a `whitespace-nowrap` title
   in the chat list stretched the page to 650–867 px. On a mobile browser the layout viewport then widens, so fixed
   popups (New chat, the image viewer) center on the wide page and open partly or wholly off screen.
2. **Unbreakable strings.** `break-words` (`overflow-wrap: break-word`) doesn't lower an element's min-content width,
   so a long URL in a title, message, search snippet or path still forces its container wider.
3. **Native `<select>`s size to their longest option.** This affects KB search's Space, Memory's Project, the chat
   list's project filter and the New chat dialog's Project.

The fix is structural: min-width floors on grid/flex children (`minmax(0,1fr)` columns, `min-w-0`), wrap-anywhere on
user content, `w-full min-w-0` on selects. Patching each page's symptom is not the fix.

## Decided layouts

### Chats (approved mockup)

On phones (below md):

- **Chat list** (`/chats`, `/projects/:key/chats`): full width.
  - The header row reads "Chats" with "+ New chat" on its right.
  - The project filter is full width and cut short with "…" when long.
  - Each chat shows its title in at most 2 lines (wrapping long words), then one line with the project key and its
    state (waiting states in amber).
- **An open chat** (`/chats/:id`):
  - The page intro ("Chats" heading, description, New chat) is hidden while a chat is open. A ‹ button in the chat
    header goes back to the list and replaces the "← All chats" link. *(Builder's call, settled here:)* ‹ goes back
    in the browser's history when the previous page was a chat list in this app (so a chat opened from a project's
    Chats tab returns there). Otherwise it goes to `/chats`.
  - The header (owner's choice: "compact") shows, top to bottom:
    - the title in at most 2 lines (wrapping long words, full title on tap/hover as today), with a ⋯ menu on its
      right that holds **End chat** (and its confirmation, as today);
    - one small line "PROJECT · agent name · program" cut short with "…";
    - the state as one pill (a waiting state is an amber button that jumps to what waits, as today);
    - one short line naming the current step ("Design · step 2 of 5 ▾"). Tapping it shows all five steps (Talk ·
      Design · Plan · Build · Finish) as today's progress row does.
  - Nothing in today's header is lost; it is only folded.
  - The thread fills the rest. Messages wrap long words and links. Code blocks and tables scroll inside their own
    box with a fade at the edge. The jump buttons (top, latest, waiting) stay.
  - The message box starts at about 2 lines and grows with the text up to about 5 lines, then scrolls. Below it is
    one row: the image button (icon only, labelled "Add images"), the one-line hint (cut short with "…"), and Send.
    Image previews show above that row as today.
- **New chat dialog and image viewer:** fit the screen with the page itself no longer too wide. The dialog's
  project and agent selects are full width.
- From md up the chats page keeps today's two-column layout.

### Task page and every project page (approved mockup)

On phones:

- **Project header:** the project key and name take one line, with the name cut short with "…" and the full name on
  hover/long-press. The **Incoming questions** link moves into the project's tab bar as its last item, labelled
  **Questions** with its count badge. Its separate row goes away. *(My call:)* it stays a link to today's
  `/questions?tab=incoming&project=KEY` (no new project route), so it never shows as the current tab; it is styled
  like a tab and always sits last, whether or not Backlog and Reports are shown. On phones only; from md up the
  header is unchanged.
- **Tab bars** that don't fit show a fade and a › at the edge that has more. This applies to the project tabs and to
  the section tabs in project settings, my settings, admin settings, AI, methodology and Hub shelves.
- **Comment box:** on phones, wherever a task is shown (the task page and the task drawer opened from the board or
  backlog, which on a phone covers the screen; *my call*), a one-line bar sits at the bottom ("Add a comment…" plus the image
  button) in place of the full comment form. Tapping it opens the full form (text, images, "Send to the agent"
  switch, Comment button) above the keyboard. Sending, or tapping away with an empty text, closes it again; a typed
  but unsent comment stays when it closes. From md up the comment form is unchanged.
- The floating "waiting on you" / jump buttons must not cover text or inputs. They sit clear of the comment bar and
  leave the content padding they need.

### Dashboard (approved mockup)

On phones:

- **Needs you** comes first, above everything else.
- The KPI numbers become one row of small cards that scrolls sideways (with the edge fade), not 8 full-width cards.
  *(My call:)* all 8 tiles stay, each with its number, label and small second line ("2 over a day old", "▲ 3 on the
  7 days before"); the mockup's 4 bare chips only showed the shape. Cards are about 130–150 px wide.
- In list rows (Chats, Agents, Running now, Projects, System), the name keeps the room and the status/value side is
  capped (about 45%) and cut short. Today the status keeps its full width and squeezes the name to one letter.

### Smaller fixes (described in the mockup, no further decision)

- **Search** (`/search`): the filters (types, Updated, match by meaning, Sort) fold behind a "Filters" button on
  phones, showing how many are set; results start at the top. Long words in snippets wrap.
- **My agents** (`/settings/agents`):
  - The "My agents" heading, intro and Add agent don't repeat above every tab and detail view on phones.
  - In an agent's details, the name has its own line, with the program badge, status and ⋯ menu below it.
  - "Search projects" stacks above "+ Add project". On the runner tab, "Machine name" stacks above "Make token".
  - Long folder paths are cut in the middle ("C:\Users\…\checkout-service") so the end stays visible, with the full
    path on hover/long-press.
- **Backlog:** the type select, Move… and the drag handle are at least 32 px tall/wide. On phones the title uses the
  row's full width, with key, points and Move… on a line below it.
- **Tables:**
  - Admin › Agents and Notification settings become stacked cards on phones (each row a card, each value labelled).
  - Tokens and Audit keep their tables, scrolling inside their box with the edge fade.
  - Admin › Users cards label the two-factor and last-seen values.
- **Methodology editor:** no card-in-card padding on phones; the editor uses the full width.
- **Clipped placeholders** (KB search box, Memory question) are shortened or wrap.
- **Project settings:** the Status segmented control fits its box at 280 px.

## Testing

- Extend `frontend/e2e/mobile.spec.ts`:
  - Visit the Chats pages (all chats, a project's chats, an open chat) with an agent conversation whose messages hold
    a long URL, a long inline-code identifier, a wide code block and a wide table.
  - Open the popups: New chat, the image viewer, main menu, search, notifications, assignee, delete confirmation,
    Add agent, New token.
  - Run at 280 and 344 px with touch/mobile emulation.
  - The overflow check must also catch content that scrolls sideways inside a vertical scroller: a box may scroll
    sideways only if it is one of the allowed kinds: code block, Markdown table, data table, command or snippet box,
    tab bar, board, the KPI row, Mermaid diagram, the KB diff view, the project settings column editor, and the AI
    usage table. *(My call:)* these last four already scroll inside their box today and keep doing so, with the edge
    fade; redesigning them is out of scope. The allowed kinds are marked explicitly in the markup (for example a
    `data-scroll-x` attribute) so the test doesn't guess. Anything else that scrolls sideways is a failure.
- A board check with an active sprint and several columns (the audit's data had no sprint, so the board's columns
  were not reviewed). The board may scroll sideways inside its own box, but cards and column headers must not clip.
- Unit tests for the new behaviour: the comment bar opening and closing and keeping a draft, the Filters fold, the
  Questions tab badge, the KPI row, and the chat header's ‹ back.
- The throwaway audit scripts used to find these problems (`frontend/e2e/zz-mobile-audit*.spec.ts`,
  `frontend/e2e/helpers/zz-measure.ts`, uncommitted) can be mined for data seeding and the measuring code, then
  deleted.

## Left to the builder

- Exact Tailwind classes, the fade implementation (mask or gradient overlay) and whether it is a shared component.
- How the one-line comment bar is built (a sheet, an expanding form), as long as it behaves as described.
- The order of work and how it splits into tasks.
- The exact copy of the Filters button and the cut-short rules, in the app's existing style.
