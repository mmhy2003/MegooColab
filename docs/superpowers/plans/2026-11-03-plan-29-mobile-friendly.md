# Mobile-friendly MegooColab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every page, popup and dialog works on a 280 px phone without sideways page scrolling. An open chat and an
open task give the content most of the screen.

**Architecture:**
- Fix the structural cause once: min-width floors on grid/flex children, `wrap-anywhere` on user content, and
  `min-w-0` selects.
- A shared `ScrollX` box marks the content allowed to scroll sideways (with an edge fade). The e2e guard then fails
  on anything else that does.
- Phone-only layouts are CSS below `md` (`max-md:` / `md:` variants), with no JS width detection, so desktop is
  untouched.

**Tech Stack:** Next.js 16, React 19, Tailwind 4.3 (`wrap-anywhere`, `max-md:`, `[field-sizing:content]`),
vitest + Testing Library, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-03-mobile-friendly-design.md` (approved mockups:
`.superpowers/brainstorm/1996-1793694540/content/chat-phone.html`, `other-pages.html`).

## Global Constraints

- **Widths:**
  - No page scrolls sideways at 280 px or wider. This covers every page, popup and dialog, signed in or out.
  - 344 px and 360–430 px must look right too.
  - Nothing changes at md (768 px) and up, except width-independent fixes (wrapping, `min-w-0`).
- **Wrapping:** `overflow-wrap: anywhere` (`wrap-anywhere`) for user content. Never `break-all` on prose.
- **Sizes:** no text under 11 px. Tap targets are at least 32 px in each dimension.
- **Nothing hidden:** everything reachable on desktop stays reachable on a phone (it may be folded behind a tap).
- **Code style:** no Prettier. Match the surrounding code's comment density and naming. Copy uses the app's plain
  style.
- **Commits:** every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Work stays on
  `feat/mobile-friendly`. No pushing.
- **Docker:** use only the `megoo-e2e` compose project for e2e. Stop the dev caddy (`megoocolab-dev-caddy-1`) while
  it runs and start it after. Never touch the user's real `megoocolab-*` containers or `cloudflared`.

## Review Focus

1. **A chat or task whose content is one long unbroken string** (a 300-character URL with no spaces) must wrap inside
   the screen and not stretch its container. This is pinned by the e2e chat data (Task 2) and by
   `ChatList.test` ("a long title stays inside").
2. **The comment bar keeps a typed but unsent comment** when it closes (tap away, Escape), and reopens with it. This
   is pinned in Task 5 (`keeps a draft when closed`).
3. **The KPI row and tab bars at exactly the width that fits:** the fade must not show when nothing is hidden. This
   is pinned in Task 1 (`no fade when it all fits`).
4. **A dropdown whose option is longer than the screen** (a project name of 200 characters) must not widen its form
   or dialog. This is pinned in Task 1 (`Select stays inside a narrow parent`) and by e2e (New chat dialog, Memory,
   KB search).
5. **The chat ‹ back button opened by a direct link** (no in-app history) must go to `/chats`, not leave the app.
   This is pinned in Task 3 (`back without history goes to all chats`).

---

### Task 1: `ScrollX`, wrapping and selects (the shared fixes)

**Files:**
- Create: `frontend/src/components/ui/ScrollX.tsx`
- Modify:
  - `frontend/src/components/ui/Tabs.tsx`
  - `frontend/src/components/ui/Select.tsx`
  - `frontend/src/components/ui/Markdown.tsx`
  - `frontend/src/components/ui/MermaidDiagram.tsx`
  - `frontend/src/components/kb/DiffView.tsx`
  - `frontend/src/components/project/ColumnEditor.tsx`
  - the command/snippet boxes (`frontend/src/components/agents/Snippet.tsx`, `frontend/src/components/ui/CopyField.tsx`)
  - the data tables on `/settings/tokens`, `/admin/audit` and AI usage (`frontend/src/components/ai/*Usage*`)
  - the board's columns scroller (`frontend/src/components/board/`)
- Test:
  - `frontend/src/components/ui/__tests__/ScrollX.test.tsx`
  - `frontend/src/components/ui/__tests__/Select.test.tsx` (create if missing)
  - `frontend/src/components/ui/__tests__/Markdown.test.tsx` (extend)

**Interfaces:**
- Produces:
  - `export function ScrollX({ children, className, innerClassName, label }: { children: React.ReactNode; className?: string; innerClassName?: string; label?: string }): React.JSX.Element`.
    It renders an outer `div.relative.min-w-0` and an inner `div` with `data-scroll-x`, `overflow-x-auto` and
    `aria-label={label}` when given. It also renders two `aria-hidden` fade overlays: `[data-fade="start"]` shows
    when `scrollLeft > 0`, and `[data-fade="end"]` shows when `scrollLeft + clientWidth < scrollWidth - 1`. Both
    update on scroll and on a `ResizeObserver` (skipped when `ResizeObserver` is undefined).
  - The convention: **every element allowed to scroll sideways carries `data-scroll-x`**. Task 2's e2e guard relies
    on it.
  - `Tabs` renders its tablist inside `ScrollX`. The tablist role and aria stay on the inner element.

- [ ] **Step 1: Write the failing tests**

```tsx
// ScrollX.test.tsx — jsdom has no layout: set the sizes on the scroller, then fire scroll
it("shows the end fade while more is hidden, and the start fade once scrolled", () => { /* scrollWidth 500, clientWidth 280, scrollLeft 0 → [data-fade=end] visible, [data-fade=start] hidden; scrollLeft 220 + scroll event → start visible, end hidden */ });
it("no fade when it all fits", () => { /* scrollWidth 280 = clientWidth 280 → neither fade visible */ });
it("marks its scroller with data-scroll-x and the given label", () => { /* getByLabelText(label) has attribute data-scroll-x */ });
// Select.test.tsx
it("Select stays inside a narrow parent", () => { /* the <select> and its wrapper have class min-w-0 */ });
// Markdown.test.tsx
it("wraps long words anywhere and marks code blocks and tables as sideways scrollers", () => { /* the prose root has class wrap-anywhere; a ```ts block's <pre> and a pipe table's wrapper each have data-scroll-x */ });
```

"Visible" means not `hidden` (the fades toggle the `hidden` class or attribute).

- [ ] **Step 2: Run to watch them fail**

Run: `cd frontend && npx vitest run src/components/ui`
Expected: FAIL. The ScrollX module is not found, Select lacks `min-w-0`, and Markdown lacks `wrap-anywhere` and
`data-scroll-x`.

- [ ] **Step 3: Implement**
  - `ScrollX` as specified in Interfaces. The fades are 1.5rem gradients from the page surface
    (`from-transparent to-surface`), plus `pointer-events-none`.
  - `Select`: add `min-w-0` to the wrapper `div` and to the `<select>`. Leave the rest as it is.
  - `Markdown`:
    - Replace `break-words` with `wrap-anywhere` on the prose root.
    - `CodeBlock`'s plain `<pre>` gets `data-scroll-x`.
    - The table wrapper becomes `<ScrollX className="my-2">`.
  - Add `data-scroll-x` to the existing sideways scrollers in each of the other files listed above, without changing
    their layout:
    - `MermaidDiagram`, `DiffView`, `ColumnEditor` and the command/snippet boxes;
    - the tokens, audit and AI usage table wrappers;
    - the board's columns scroller.
  - The tables and the board use `ScrollX` where they are a plain `overflow-x-auto` div today.

- [ ] **Step 4: Run to watch them pass, plus the whole web suite**

Run: `cd frontend && npx vitest run src/components/ui && npx vitest run && npx tsc --noEmit -p . && npx eslint src`
Expected: all pass; tsc and eslint clean.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src && git commit -m "feat(ui): ScrollX marks what may scroll sideways; long words wrap; selects stay inside"
```

---

### Task 2: The phone guard (e2e), written to fail first

**Files:**
- Modify: `frontend/e2e/mobile.spec.ts`
- Mine, then delete:
  - `frontend/e2e/zz-mobile-audit.spec.ts`
  - `frontend/e2e/zz-mobile-audit-2.spec.ts`
  - `frontend/e2e/helpers/zz-measure.ts`
  - These are uncommitted throwaway audit scripts. Their data seeding and measuring code are the starting point.

**Interfaces:**
- Consumes: Task 1's `data-scroll-x` convention.

- [ ] **Step 1: Rewrite `overflow(page)` in `mobile.spec.ts`**
  - It returns the page-overflow culprits, as today.
  - It also returns every element whose computed `overflow-x` is `auto` or `scroll`, whose
    `scrollWidth > clientWidth + 1`, and which has no `data-scroll-x`. These are reported as
    `"<tag>[aria-label] .class… scrolls sideways by Npx"`.
  - The old `contained()` exemption goes.

- [ ] **Step 2: Extend "every page fits a 280-pixel screen" into a loop over `[280, 344]`**
  - Each width gets its own context: `isMobile: true`, `hasTouch: true`, viewport height 653.
  - Add the pages the audit found missing:
    - `/chats`, `/projects/MOB/chats`
    - `/projects/MOB`, `/kb/<project space id>`, `/kb/doc/<id>`
    - `/hub`, `/hub/new-mcp`, `/hub/new-skill`
    - `/admin`, `/settings`, `/change-password`
  - Signed out: `/login`, `/forgot`.
  - Seeding:
    - a task comment, a KB document and a question body, each holding the spec's long content: a 120-character URL,
      a 55-character inline-code identifier, a fenced code block with a 150-character line, and a 6-column pipe
      table;
    - a project name of 60 characters;
    - a team name long enough to make the KB search Space option wider than 280 px.
  - Keep the existing assertions after the loop.

- [ ] **Step 3: Add `test("chats on a phone", …)` with a fake runner**
  - The setup is as `chats.spec.ts` does it: `buildBinaries`, `mintLinkedRunnerToken`, `startRunner`.
  - Scenario:
    `[onPrompt(BRAINSTORM, say(LONG_MSG), mcp("submit_design", { key: "MOC-1", markdown: DESIGN }))]` on a new
    project `MOC`, with sprints off.
  - Start a chat from the New chat dialog at desktop size. The first message holds the 120-character URL, and an
    image is attached with `fixtures/screenshot.png`.
  - Wait for the design to show.
  - Then, at 280 and 344 px:
    - `overflow()` is `[]` on `/chats`, `/projects/MOC/chats` and the open chat.
    - The open chat's thread (`[data-thread]`) is at least 45% of the viewport height.
    - The New chat dialog, the image viewer (`Open screenshot.png`) and the chat's ⋯ menu each lie within
      `0 … width` (reuse `onScreen`).
    - The main menu, search, notifications, the assignee list, the delete-task confirmation, Add agent and New token
      also lie on screen.
  - Clean up the runner and the agent as `chats.spec.ts` does.

- [ ] **Step 4: Add `test("the board on a phone", …)`**
  - Project `MOB` with sprints off (`PATCH /api/projects/MOB {sprints_enabled: false}`) and three tasks.
  - At 280 px, `/projects/MOB/board` shows `overflow() == []`, and the first column's header and its first card are
    fully visible.
  - Restore sprints afterwards if later specs need them.

- [ ] **Step 5: Delete the zz files, then run the guard to watch it fail**

Run: bring up a fresh `megoo-e2e` stack (as in the scratchpad `audit-run.sh`), then
`cd frontend && npx playwright test mobile`.
Expected: FAIL. The Chats pages scroll sideways (page width about 650–867), the chat thread is under 45% of the
height, and the New chat dialog and image viewer are off screen. Memory, KB search and Search fail on width. Tear the
stack down after the run.

- [ ] **Step 6: Commit (the guard is red until Task 9)**

```bash
git add -A frontend/e2e && git commit -m "test(e2e): phones at 280 and 344 px, chats and popups included; sideways scrollers must be marked"
```

---

### Task 3: Chats on a phone

**Files:**
- Modify:
  - `frontend/src/components/chats/ChatsPage.tsx`
  - `frontend/src/components/chats/ChatList.tsx`
  - `frontend/src/components/chats/ChatView.tsx`
  - `frontend/src/components/chats/ChatComposer.tsx`
  - `frontend/src/components/chats/EndChatButton.tsx`
  - `frontend/src/components/chats/NewChatDialog.tsx`
- Test:
  - `frontend/src/components/chats/__tests__/ChatsPage.test.tsx`
  - `ChatList.test.tsx`, `ChatView.test.tsx` and `NewChatDialog.test.tsx` (extend)

**Interfaces:**
- Consumes: `ScrollX` and the `data-scroll-x` convention (Task 1).
- Produces:
  - `export function useEndChat(chat: Chat, agentRunning: boolean): () => Promise<void>` in `EndChatButton.tsx`.
    `EndChatButton` uses it, and so does the phone menu.
  - `export function ChatBack({ fallback }: { fallback: string }): React.JSX.Element` in `ChatView.tsx` (or its own
    file):
    - a ‹ button labelled "All chats";
    - calls `router.back()` when `document.referrer` is this origin and its path starts with `/chats` or matches
      `/projects/[^/]+/chats`;
    - otherwise calls `router.push(fallback)`.

- [ ] **Step 1: Write the failing tests**

```tsx
// ChatsPage.test.tsx
it("on a phone an open chat hides the page intro", () => { /* with chatId: the PageHeader wrapper has class max-md:hidden; the old "← All chats" link is gone */ });
it("the grid has a single shrinking column on phones", () => { /* the grid element has class grid-cols-[minmax(0,1fr)] */ });
// ChatList.test.tsx
it("a long title stays inside: two lines, wrapping anywhere", () => { /* title span has classes line-clamp-2 and wrap-anywhere, not truncate */ });
// ChatView.test.tsx
it("the phone header folds End chat into a menu and the steps into one line", async () => { /* a button "Chat actions" opens a menu with "End chat"; a button named /Design · step 2 of 5/ toggles the Progress list (aria-expanded) */ });
it("back without history goes to all chats", async () => { /* referrer "" → clicking "All chats" pushes "/chats" */ });
it("back from a project's chat list goes back", async () => { /* referrer `${origin}/projects/AUD/chats` → router.back called */ });
it("the header names project, agent and program on one line", () => { /* text "AUD · Root Admin's Claude Code · Claude Code" in an element with class truncate */ });
// NewChatDialog.test.tsx
it("its selects stay inside the dialog", () => { /* both selects have class min-w-0 (Select from Task 1) */ });
```

- [ ] **Step 2: Run to watch them fail**

Run: `cd frontend && npx vitest run src/components/chats`
Expected: the new tests FAIL. The existing tests pass.

- [ ] **Step 3: Implement (desktop unchanged)**
  - **`ChatsPage`:**
    - The grid gets `grid-cols-[minmax(0,1fr)]` (keeping `md:grid-cols-[18rem_minmax(0,1fr)]`), and `aside` and
      `section` get `min-w-0`.
    - With `chatId`, the `PageHeader` is wrapped in `max-md:hidden`, and the `← All chats` link is removed.
    - The project's chat list (with `projectKey`) shows a phone header row: "Chats" on the left and `newChat` on
      the right.
  - **`ChatList`:** the title span becomes `line-clamp-2 wrap-anywhere` (in place of `truncate`).
  - **`ChatView` header:**
    - The title gets `wrap-anywhere`. `ChatBack` (with `fallback="/chats"`) sits to its left as `md:hidden`.
    - On the right: `EndChatButton` as `max-md:hidden`, and a `md:hidden` ⋯ `DropdownMenu`
      (`components/shadcn/dropdown-menu`) labelled "Chat actions" with an "End chat" item calling `useEndChat`.
      Only when `c.can_act && c.status === "open"`.
    - On phones the chips row shows one `truncate` line "KEY · agent name · program". The state pill stays as it is.
    - `ChatProgress` moves behind a `md:hidden` toggle button reading `"{current step label} · step {i+1} of 5"`
      (`"Finished"` when finished) with `aria-expanded`. From md up `ChatProgress` shows as today.
    - The thread container (`[data-thread]`) gets `wrap-anywhere`.
  - **`ChatComposer` on phones:**
    - The textarea becomes `max-md:min-h-[3.25rem] max-md:max-h-32 max-md:[field-sizing:content]`; it stays
      `min-h-20` from md up.
    - `<ImageAttach>` stays above one row: the image button (icon-only on phones, accessible name "Add images"), the
      `intentText` line `truncate`, and Send.
    - Image previews stay where `ImageAttach` renders them.

- [ ] **Step 4: Run the chats tests, then the whole web suite**

Run: `cd frontend && npx vitest run src/components/chats && npx vitest run && npx tsc --noEmit -p . && npx eslint src`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src && git commit -m "feat(chats): fit a 280 px phone; an open chat gets the screen, its header folds"
```

---

### Task 4: Project header, the Questions tab, tab bar fades

**Files:**
- Modify: `frontend/src/app/(app)/projects/[key]/layout.tsx`
- Test: `frontend/src/app/(app)/projects/[key]/__tests__/layout.test.tsx` (create)

**Interfaces:**
- Consumes: `ScrollX` (Task 1).

- [ ] **Step 1: Write the failing tests**

```tsx
it("on phones Questions is the tab bar's last link, with its count", () => { /* nav "Project" links end with "Questions" (class md:hidden) whose href is /questions?tab=incoming&project=AUD and which holds the badge "2 need an answer"; it has no aria-current */ });
it("Questions is last with sprints off too", () => { /* sprints_enabled false → links Board, Chats, Settings, Questions */ });
it("from md up the Incoming questions link stays where it is", () => { /* the separate "Incoming questions" link outside the nav has class max-md:hidden */ });
it("the project name stays on one line on phones", () => { /* the h1 has class max-md:truncate and a title attribute with the full name */ });
it("the tab bar is a ScrollX", () => { /* nav "Project" has data-scroll-x */ });
```

- [ ] **Step 2: Run to watch them fail**

Run: `cd frontend && npx vitest run "src/app/(app)/projects/\[key\]"`
Expected: FAIL.

- [ ] **Step 3: Implement**
  - `IncomingQuestions` takes a `variant: "tab" | "link"` prop.
    - The `"tab"` variant is the last item in the `<nav aria-label="Project">` with `md:hidden`, styled like a tab
      link: label "Questions" plus the same badge (the badge keeps today's `aria-label`). It is never
      `aria-current`.
    - The `"link"` variant is today's `ml-auto` link, now with `max-md:hidden`, so desktop is unchanged as the spec
      says.
  - The `nav` is rendered through `ScrollX` with `label="Project"`.
  - The `h1` gets `max-md:truncate max-md:w-full` and `title={`${p.key} ${p.name}`}`.

- [ ] **Step 4: Run them to pass, then the web suite (command as Task 3).**

- [ ] **Step 5: Commit** `feat(project): one-line project header; Questions in the tab bar; tab bars show there's more`

---

### Task 5: The one-line comment bar on phones

**Files:**
- Create: `frontend/src/components/task/PhoneComposer.tsx`
- Modify:
  - `frontend/src/components/task/TaskView.tsx` (wrap the `CommentBox` in the sticky `data-composer` block)
  - `frontend/src/components/task/CommentBox.tsx` (after a successful `onSubmit` it calls
    `useContext(PhoneComposerContext)?.close()`; outside a `PhoneComposer` the context is `null` and nothing
    happens)
- Test: `frontend/src/components/task/__tests__/PhoneComposer.test.tsx`

**Interfaces:**
- Produces:
  - `export function PhoneComposer({ children, label }: { children: React.ReactNode; label: string }): React.JSX.Element`
  - Below md, while closed, it shows a `md:hidden` bar:
    - a button with accessible name `label` ("Add a comment…") that opens it;
    - an image button ("Add images") that opens it and then clicks the first `input[type=file]` inside `children`.
  - `children` are always mounted, wrapped in `max-md:hidden` while closed, so a draft survives.
  - Open, it shows the children and focuses the first `textarea`.
  - It closes when:
    - focus leaves the wrapper and the textarea is empty;
    - Escape is pressed (the text is kept);
    - its child calls `close()` from `export const PhoneComposerContext = createContext<{ close: () => void } | null>(null)`,
      as `CommentBox` does after a send.
  - From md up the bar never shows, and the children always show.

- [ ] **Step 1: Write the failing tests**

```tsx
it("starts as a one-line bar and opens on tap", async () => { /* bar button "Add a comment…" visible; the textarea's wrapper has max-md:hidden until clicked; after click the wrapper has no max-md:hidden and the textarea has focus */ });
it("keeps a draft when closed", async () => { /* type "half a thought", press Escape → bar shows; open again → textarea value "half a thought" */ });
it("closes on blur only when empty", async () => { /* empty + focus elsewhere → closed; with text + focus elsewhere → stays open */ });
it("closes after sending", async () => { /* CommentBox inside, submit resolves → closed, textarea empty */ });
it("the image button opens it and the file chooser", async () => { /* clicking "Add images" on the bar → open, and the file input's click() was called (spy) */ });
```

- [ ] **Step 2: Run to watch them fail**

Run: `cd frontend && npx vitest run src/components/task/__tests__/PhoneComposer.test.tsx`
Expected: FAIL (the module is missing).

- [ ] **Step 3: Implement**
  - `PhoneComposer` as in Interfaces.
  - In `TaskView`, the `data-composer` block's child becomes
    `<PhoneComposer label="Add a comment…"><CommentBox … /></PhoneComposer>`.
  - The left column's `pb-4` becomes `pb-4 max-md:pb-16`, so the end of the content can scroll clear of the
    floating jump buttons.
  - The task drawer uses the same `TaskView`, so it gets the bar too (spec, my call).

- [ ] **Step 4: Run the task tests, then the web suite**

Run: `cd frontend && npx vitest run src/components/task && npx vitest run && npx tsc --noEmit -p . && npx eslint src`
Expected: all pass. `CommentBox.test` and `TaskDrawer.test` stay green.

- [ ] **Step 5: Commit** `feat(task): a one-line comment bar on phones that opens when tapped and keeps the draft`

---

### Task 6: Dashboard on a phone

**Files:**
- Modify:
  - `frontend/src/components/dashboard/Dashboard.tsx`
  - `frontend/src/components/dashboard/Kpis.tsx`
  - the row components `ChatsCard.tsx`, `AgentsCard.tsx`, `RunningNow.tsx`, `ProjectsCard.tsx`, `SystemCard.tsx`
- Test: `frontend/src/components/dashboard/__tests__/Dashboard.test.tsx` and `Kpis.test.tsx` (extend)

**Interfaces:**
- Consumes: `ScrollX` (Task 1).

- [ ] **Step 1: Write the failing tests**

```tsx
// Dashboard.test.tsx
it("on a phone, Needs you comes before the numbers", () => { /* in document order, a "Needs you" region with class md:hidden precedes the Kpis; the in-grid Needs you has class max-md:hidden */ });
// Kpis.test.tsx
it("all 8 tiles stay, each with its second line, in a sideways row on phones", () => { /* 8 tiles; "2 over a day old" present; the row has data-scroll-x; each tile has class max-md:w-36 and shrink-0 */ });
// ChatsCard.test.tsx (one row component stands for all five)
it("the status side is capped so the name keeps its room", () => { /* the status span has max-w-[45%] and truncate */ });
```

- [ ] **Step 2: Run to watch them fail.** `cd frontend && npx vitest run src/components/dashboard`. Expected: FAIL.

- [ ] **Step 3: Implement**
  - `Dashboard` renders `NeedsYou` twice: one `md:hidden` copy above `Kpis`, and the existing one wrapped
    `max-md:hidden`. Spec ruling, recorded in the ledger: one component, two placements by width, so desktop is
    unchanged.
  - `Kpis`:
    - On phones, a `ScrollX` containing `flex gap-2.5`, with tiles `max-md:w-36 shrink-0`.
    - From md up, today's grid (`md:grid md:grid-cols-[repeat(auto-fit,minmax(8.5rem,1fr))]`).
  - Row components: the name `min-w-0 flex-1 truncate`; the status/value `min-w-0 max-w-[45%] shrink truncate`.

- [ ] **Step 4: Run them to pass, then the web suite.**

- [ ] **Step 5: Commit** `feat(dashboard): Needs you first on phones; the numbers as a sideways row; names keep their room`

---

### Task 7: Search filters fold on phones

**Files:**
- Modify: `frontend/src/components/search/SearchResults.tsx`
- Test: `frontend/src/components/search/__tests__/SearchResults.test.tsx` (extend)

- [ ] **Step 1: Write the failing tests**

```tsx
it("on phones the filters fold behind a Filters button that counts what is set", async () => { /* a button "Filters (2)" (kind + updated set) with aria-expanded=false and class md:hidden; the aside "Filters" has max-md:hidden until clicked */ });
it("long words in a result wrap", () => { /* the result snippet element has wrap-anywhere */ });
```

- [ ] **Step 2: Run to watch them fail.** `cd frontend && npx vitest run src/components/search`. Expected: FAIL.

- [ ] **Step 3: Implement**
  - A `md:hidden` toggle button labelled `Filters` (plus ` (N)` when N > 0). N counts each set kind, project, type,
    status, assignee, label and updated value, plus "match by meaning" when on. The sort is not counted.
  - The `aside` gets `max-md:hidden` while folded.
  - `ResultItem`'s title and snippet get `wrap-anywhere`.

- [ ] **Step 4: Run to pass, then the web suite.**

- [ ] **Step 5: Commit** `feat(search): filters fold on phones; long words in results wrap`

---

### Task 8: My agents on a phone

**Files:**
- Modify:
  - `frontend/src/app/(app)/settings/agents/page.tsx`
  - `frontend/src/components/agents/AgentsTab.tsx`
  - `frontend/src/components/agents/ProjectBindings.tsx`
  - `frontend/src/components/agents/AddMachine.tsx`
- Create: `frontend/src/lib/paths.ts`
- Test:
  - `frontend/src/lib/__tests__/paths.test.ts`
  - `frontend/src/components/agents/__tests__/ProjectBindings.test.tsx`, `AddMachine.test.tsx` and the page's
    existing tests (extend)

**Interfaces:**
- Produces: `export function middleTruncate(path: string, max: number): string` in `lib/paths.ts`:
  - it keeps the first segment and as many trailing segments as fit, joined by `…`;
  - it returns the path unchanged when `path.length <= max`;
  - `\` and `/` both count as separators, and the original separator is kept.

- [ ] **Step 1: Write the failing tests**

```ts
// paths.test.ts
expect(middleTruncate("C:\\Users\\hammad\\Projects\\checkout-service", 28)).toBe("C:\\…\\Projects\\checkout-service");
expect(middleTruncate("/home/me/work/checkout-service", 40)).toBe("/home/me/work/checkout-service");
expect(middleTruncate("/home/me/a/very/deep/tree/checkout-service", 24)).toBe("/home/…/checkout-service");
```

```tsx
// page tests
it("on phones the header and tabs hide while an agent's details are open", () => { /* ?agent=a1 → PageHeader and tablist wrapped in max-md:hidden */ });
// AgentsTab: the detail header puts the name on its own line on phones
it("the agent's name has its own line on phones", () => { /* h2 has max-md:basis-full and wrap-anywhere, not truncate on phones */ });
// ProjectBindings
it("Search projects stacks above Add project on phones", () => { /* the row has max-sm:flex-col */ });
it("a long folder is cut in the middle, the full path in its title", () => { /* text uses middleTruncate(…, 40); title attribute is the full path */ });
// AddMachine
it("Machine name stacks above Make token on phones", () => { /* the form row has max-sm:flex-col and the input wrapper max-sm:w-full */ });
```

- [ ] **Step 2: Run to watch them fail.** `cd frontend && npx vitest run src/lib src/components/agents "src/app/(app)/settings"`. Expected: FAIL.

- [ ] **Step 3: Implement as the tests state.** The subtitle (intro) of `My agents` gets `max-md:hidden` on every tab.
The agent header row becomes `flex flex-wrap`: the name is `max-md:basis-full`, with the badge, status and ⋯ menu on
the next line.

- [ ] **Step 4: Run to pass, then the web suite.**

- [ ] **Step 5: Commit** `feat(agents): My agents fits a phone: no repeated header, stacked inputs, paths cut in the middle`

---

### Task 9: The rest (backlog, tables as cards, labels, editor, placeholders), then the guard goes green

**Files:**
- Modify:
  - `frontend/src/components/sprint/SprintPanel.tsx` (the backlog row)
  - `frontend/src/app/(app)/admin/agents/page.tsx`
  - `frontend/src/components/notifications/NotificationPrefs.tsx`
  - `frontend/src/app/(app)/admin/users/page.tsx`
  - `frontend/src/components/workflow/MethodologyEditor.tsx` and `frontend/src/app/(app)/admin/methodology/page.tsx`
  - `frontend/src/components/kb/KbReader.tsx`
  - `frontend/src/components/memory/AskMemory.tsx`
  - `frontend/src/components/project/StatusSection.tsx`
- Test: the existing tests next to each file (extend), and `frontend/e2e/mobile.spec.ts` (from Task 2)

- [ ] **Step 1: Write the failing unit tests**

```tsx
// SprintPanel: tap targets and the phone row
it("the backlog row's controls are tap-sized and the title takes the row on phones", () => { /* drag button and Move select have min-h-8 min-w-8; the title button has max-sm:basis-full */ });
// admin agents page
it("on phones each agent is a card with labelled values", () => { /* a md:hidden list where each item shows "Status" and "Current run" labels; the table is max-md:hidden */ });
// NotificationPrefs
it("on phones each event is a card with its channels", () => { /* md:hidden list with the event text and a labelled switch per channel; the table is max-md:hidden */ });
// admin users
it("the user card labels two-factor and last seen", () => { /* text "Two-factor: Off" and "Last seen: Today, …" on the phone card */ });
// MethodologyEditor
it("the editor uses the full width on phones", () => { /* the inner card has max-md:border-0 max-md:p-0 */ });
// KbReader, AskMemory
it("placeholders fit a phone", () => { /* KbReader placeholder "Search…"; AskMemory placeholder ≤ 32 characters */ });
// StatusSection
it("the status choices fit at 280 px", () => { /* the segmented control has flex-wrap */ });
```

- [ ] **Step 2: Run to watch them fail.** `cd frontend && npx vitest run`. Expected: only the new tests fail.

- [ ] **Step 3: Implement as the tests state.**
  - Phone cards render the same data as their table rows. The tables keep `ScrollX` and are hidden only below md
    where a card list replaces them.
  - The Tokens and Audit tables stay as tables (inside `ScrollX`).

- [ ] **Step 4: Run the web suite, tsc and eslint.**

Run: `cd frontend && npx vitest run && npx tsc --noEmit -p . && npx eslint src`
Expected: all pass.

- [ ] **Step 5: Run the phone guard and the whole e2e suite on a fresh stack**

Run: a fresh `megoo-e2e` stack, then `cd frontend && npx playwright test`.
Expected: all pass, including `mobile.spec.ts`'s three tests at 280 and 344 px. If the guard names a box that still
scrolls sideways or a page that still overflows, fix it here (with a unit test where it is component logic), and
ledger anything outside this plan's files as a `Ruling:`. Tear the stack down after.

- [ ] **Step 6: Commit**

```bash
git add -A frontend && git commit -m "feat(mobile): backlog, tables, labels and editor fit a phone; the 280 px guard is green"
```
