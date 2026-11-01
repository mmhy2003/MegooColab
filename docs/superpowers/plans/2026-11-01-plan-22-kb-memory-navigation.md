# Getting around the Knowledge Base and Memory — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reading the next Knowledge Base file or Memory entity is one click, a named Back button returns where you came
from, and the top bar's trail shows names across the whole app.

**Architecture:** Frontend only.
- A module-level **trail store** (`lib/trail.ts`, shaped like `lib/title.ts`) lets each page state its trail, and the
  Header renders it. A path-based fallback names the static pages.
- A per-tab **navigation recorder** (`lib/backNav.ts`) remembers, for each reading area, the page the person came
  from. `BackLink` shows it, or falls back to one level up.
- A shared **SideListLayout** gives the Knowledge Base (folder tree with files) and Memory (entity list) the same
  "list on the left, content on the right" shape. On a phone the list sits behind a button.

**Tech Stack:** Next.js App Router (client pages), React, TanStack Query, Tailwind, Vitest + Testing Library,
Playwright.

**Spec:** `docs/superpowers/specs/2026-11-01-kb-memory-navigation-design.md`

## Global Constraints

- Work on branch `feat/plan-22-kb-memory-navigation`, cut from `develop` at `ff0c66a`.
- **Frontend only:** no backend change and no new npm dependency.
- **Copy, exactly:**
  - the Back link reads `← Back to {label}`;
  - the phone list buttons read `Files` (Knowledge Base) and `Entities` (Memory);
  - the button for a collapsed trail is `…`, with the accessible name `Show full path`;
  - a crumb whose name is loading shows `…`, with the accessible name `Loading`;
  - the pager links read `← {title}` and `{title} →`, inside `nav` named `Folder`;
  - the Knowledge Base search box has the accessible name `Search the Knowledge Base` and the placeholder
    `Search the Knowledge Base…`.
- **The trail:**
  - It never shows a raw ID. Its last crumb never links.
  - No crumb links to a redirect-only address: `/admin`, `/settings`, `/kb/doc`, `/memory/entity`,
    `/projects/<key>/tasks`. Those crumbs are plain text.
  - It stays a `nav` named `Breadcrumb`.
- **Storage keys:**
  - `megoo.nav` (sessionStorage): the navigation record;
  - `kb.open.<spaceId>` (localStorage): a space's open folders;
  - `memory.filter` (sessionStorage): the Memory filter;
  - `memory.ask` (sessionStorage): the last Ask.
- **Storage access:**
  - Every storage read and write sits in `try/catch`. When storage fails, the page starts fresh and still works.
  - Read storage in `useState` initializers. Pages under `(app)` render only after `useMe` resolves on the client, so
    this causes no hydration mismatch.
- Access is unchanged: the lists show only what the existing endpoints return.
- **Tests and tooling:**
  - Unit tests: `cd frontend && npx vitest run <path>`. Lint: `npx eslint <paths>`. Types: `npx tsc --noEmit`.
  - End-to-end runs use only the `megoo-e2e` compose project.
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Storage that throws** (private window, blocked site data): the Knowledge Base tree, the Memory page and Back
   still render; nothing is remembered. Tests are in Tasks 3, 5 and 6.
2. **A document opened straight from a link** (new tab, notification), with no recorded origin: Back leads to its
   folder and names it. Test in Task 5.
3. **Remembered open folders that no longer exist** (deleted or moved since): they are ignored and nothing crashes.
   Test in Task 5.
4. **Following a link inside the reading area into another space**, then reading on: Back still leads to the
   original origin. Coming back to the area from another page resets the origin. Test in Task 3.
5. **The task drawer over the board:** its trail shows while it is open, and the board's trail returns when it
   closes. Test in Task 1.

---

### Task 1: The trail store and the top bar

**Files:**
- Create: `frontend/src/lib/trail.ts`
- Modify: `frontend/src/components/shell/Header.tsx` (replace `crumbs()` and the `nav` rendering)
- Test: `frontend/src/lib/__tests__/trail.test.tsx`, `frontend/src/components/shell/__tests__/Header.test.tsx`

**Interfaces:**
- Produces:
  - `type Crumb = { label: string | null; href?: string }`. A `null` label means it is still loading.
  - `type Trail = { crumbs: Crumb[]; backName?: string }`
  - `useTrail(crumbs: Crumb[], opts?: { backName?: string }): void`: the page's trail.
  - `useRecordTrail(crumbs: Crumb[], opts?: { backName?: string }): void`: a record shown over the page, such as a
    task in the drawer.
  - `useShownTrail(pathname: string): Trail`: the top registered trail. A record wins over a page, and among equals
    the latest wins, as in `lib/title.ts`. With nothing registered, it returns `{ crumbs: pathTrail(pathname) }`.
  - `pathTrail(pathname: string): Crumb[]`
  - `backNameOf(trail: Trail): string | null`: `backName`, else the last crumb's label.
- The store is a `Map` with a subscribe/notify pair, read through `useSyncExternalStore`, so the Header re-renders
  when a page registers or unregisters. Effects compare crumbs by `JSON.stringify`.

- [ ] **Step 1: Write the failing tests** in `lib/__tests__/trail.test.tsx`:

```ts
it.each([
  ["/", [{ label: "Dashboard" }]],
  ["/kb/search", [{ label: "Knowledge Base", href: "/kb" }, { label: "Search" }]],
  ["/admin/users", [{ label: "Admin" }, { label: "Users" }]],
  ["/settings/tokens", [{ label: "Settings" }, { label: "Access tokens" }]],
  ["/projects/new", [{ label: "Projects", href: "/projects" }, { label: "New project" }]],
  ["/teams/3f9a2c4e-1b2d-4c3e-8f00-123456789abc", [{ label: "Teams", href: "/teams" }, { label: null }]],
  ["/nowhere/at-all", [{ label: "nowhere", href: "/nowhere" }, { label: "at-all" }]],
])("pathTrail(%s)", (path, want) => expect(pathTrail(path)).toEqual(want));
```

Labels for the static segments match the sidebar:
- `projects` Projects, `chats` Chats, `questions` Questions, `kb` Knowledge Base, `memory` Memory, `teams` Teams,
  `notifications` Notifications, `search` Search, `admin` Admin, `settings` Settings;
- under admin: `agents` Agents, `ai` AI, `audit` Audit log, `git` Git, `methodology` Methodology,
  `settings` Settings, `users` Users;
- under settings: `agents` My agents, `notifications` Notifications, `profile` Profile, `tokens` Access tokens;
- `projects/new` New project.

A segment matching `/^[0-9a-f]{8}-[0-9a-f]{4}-/i` becomes `{ label: null }`.

Also write:
- `it("a page's trail replaces the path trail, and the path trail returns when it unmounts")`;
- `it("a record's trail shows over the page's and the page's returns when the record closes")`. This is Review
  Focus 5: mount a page with `useTrail`, then a record with `useRecordTrail`, then unmount the record;
- `it("backNameOf prefers backName, then the last label")`.

- [ ] **Step 2: Run them and see them fail**

Run: `npx vitest run src/lib/__tests__/trail.test.tsx`
Expected: FAIL. Cannot find module `@/lib/trail`.

- [ ] **Step 3: Implement `lib/trail.ts`** with the interfaces above.

- [ ] **Step 4: Add Header tests** to `Header.test.tsx`:
- `it("shows the trail's names, links all but the last, and a loading crumb as …")`: a page registers
  `[{label:"Teams",href:"/teams"},{label:null}]`. Expect a link `Teams` and an element named `Loading` with text `…`.
- `it("collapses a trail of more than three crumbs behind a Show full path button on narrow screens")`. The full
  trail renders in a `hidden sm:inline` span. The compact span (`sm:hidden`) holds the first crumb, a button `…`
  named `Show full path`, and the last crumb. Clicking the button shows every crumb in the compact span.

- [ ] **Step 5: Change `Header.tsx`** to render `useShownTrail(usePathname()).crumbs` as specified. Delete `crumbs()`.

- [ ] **Step 6: Run tests, lint and types**

Run: `npx vitest run src/lib/__tests__/trail.test.tsx src/components/shell && npx eslint src/lib/trail.ts src/components/shell && npx tsc --noEmit`
Expected: all PASS, no lint or type errors.

- [ ] **Step 7: Commit** `feat(nav): the top bar's trail shows names`

### Task 2: Trails for the pages that show a record

**Files:**
- Modify:
  - `frontend/src/app/(app)/projects/[key]/layout.tsx`
  - `frontend/src/components/task/TaskView.tsx`
  - `frontend/src/components/chats/ChatView.tsx`
  - `frontend/src/app/(app)/questions/[id]/page.tsx`
  - `frontend/src/app/(app)/teams/[id]/page.tsx`
  - `frontend/src/components/shell/NotFound.tsx`
- Test: `frontend/src/app/(app)/__tests__/trails.test.tsx`. Mirror `titles.test.tsx` (the same `serve`/`show`
  helpers), plus a `Probe` that renders `useShownTrail(pathname).crumbs.map(c => c.label ?? "…").join(" › ")`.

**Interfaces:**
- Consumes: `useTrail` and `useRecordTrail` from Task 1.

- [ ] **Step 1: Write the failing tests:**

```ts
it("a project's board", ...)        // pathname /projects/pay/board → "Projects › Payments › Board"
it("a project's chats tab", ...)    // /projects/pay/chats → "Projects › Payments › Chats"
it("a task page", ...)              // ProjectLayout + TaskPage, task PAY-12 → "Projects › Payments › PAY-12"
it("a chat", ...)                   // ChatView with title "Fix the empty email crash" → "Chats › Fix the empty email crash"
it("a team", ...)                   // teams/[id] → "Teams › Platform"
it("a question", ...)               // questions/[id] → "Questions › Q-3 Which retry policy?"
it("a record that is not found", ...) // the task 404 case from titles.test.tsx → "Page not found"
```

Crumb links to check:
- `Projects` → `/projects`;
- the project name → `/projects/<KEY>/board`;
- `Chats` → `/chats`, `Teams` → `/teams`, `Questions` → `/questions`.

- [ ] **Step 2: Run and see them fail**

Run: `npx vitest run "src/app/(app)/__tests__/trails.test.tsx"`
Expected: FAIL. The trails show path segments such as `pay`, `board` and `…`.

- [ ] **Step 3: Add the trail calls:**
- **Project layout:** `useTrail` with Projects, the project's `name` (null while loading), then the tab label. Add
  `chats: "Chats"` to the tab labels. A task page has no tab crumb.
- **`TaskView`:** `useRecordTrail`.
- **`ChatView`:** `useRecordTrail`.
- **Question page:** `useTrail`, with the last label `${ref} ${title}`.
- **Team page:** `useTrail`.
- **`NotFound`:** `useRecordTrail([{ label: "Page not found" }])`.

- [ ] **Step 4: Run tests, lint and types**

Run: `npx vitest run "src/app/(app)" src/components && npx eslint src/app src/components && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit** `feat(nav): trails name projects, tasks, chats, teams and questions`

### Task 3: Where you came from

**Files:**
- Create:
  - `frontend/src/lib/stored.ts`
  - `frontend/src/lib/backNav.ts`
  - `frontend/src/components/nav/NavRecorder.tsx`
  - `frontend/src/components/nav/BackLink.tsx`
- Modify: `frontend/src/app/(app)/layout.tsx`. Mount `<Suspense fallback={null}><NavRecorder /></Suspense>` inside
  the layout's root `div`. The Suspense is needed because `NavRecorder` uses `useSearchParams`.
- Test: `frontend/src/lib/__tests__/backNav.test.ts`, `frontend/src/components/nav/__tests__/BackLink.test.tsx`

**Interfaces:**
- Consumes: `useShownTrail`, `backNameOf` (Task 1).
- Produces:
  - `useStoredState<T>(key: string, initial: T, where: "session" | "local"): [T, (next: T) => void]`. It reads in
    the initializer, writes on set, and swallows storage errors.
  - `type Area = "kb-read" | "kb-search" | "memory-read"`
  - `areaOf(url: string): Area | null`:
    - `/kb/search…` gives `kb-search`;
    - `/kb/doc/<id>…` and `/kb/<spaceId>…` (not `search` or `doc`) give `kb-read`;
    - `/memory/entity/<id>…` gives `memory-read`;
    - anything else gives `null`.
  - `type Origin = { url: string; label: string }`
  - `recordVisit(url: string, label: string | null): void`. The state `{ current, origins }` lives in sessionStorage
    under `megoo.nav`.
    - Same URL as `current`: update `current.label` when `label` is not null.
    - Otherwise: when `areaOf(url)` is not null, differs from `areaOf(current.url)`, and `current.label` is set,
      set `origins[areaOf(url)] = current`. Then `current = { url, label }`.
  - `originFor(area: Area): Origin | null`
  - `NavRecorder()`: calls `recordVisit(pathname + (search ? "?" + search : ""), backNameOf(useShownTrail(pathname)))`
    in an effect on both values.
  - `BackLink({ area, fallback }: { area: Area; fallback: { href: string; label: string } })`: a `Link` to the
    origin, or to the fallback, with the text `← Back to {label}`.

- [ ] **Step 1: Write the failing tests** in `backNav.test.ts`:
- `it("areaOf sorts addresses into reading areas")`, with the cases above.
- `it("arriving in an area from elsewhere records where you were")`: visit `/projects/PAY/board?task=PAY-12` with
  label `PAY-12`, then `/kb/doc/d1`. `originFor("kb-read")` is `{ url: "/projects/PAY/board?task=PAY-12", label: "PAY-12" }`.
- `it("moving inside the area keeps the origin, across spaces too")`: then visit `/kb/s2?folder=f1` and `/kb/doc/d9`.
  The origin is unchanged. This is Review Focus 4.
- `it("coming back to the area from another page resets the origin")`
- `it("a label that arrives after the address is kept for the page")`: `recordVisit(u, null)`, then
  `recordVisit(u, "Payments")`, then a move into an area. The origin's label is `Payments`.
- `it("works without storage")`: stub `sessionStorage.getItem` and `setItem` to throw. `recordVisit` does not throw
  and `originFor` returns null. This is Review Focus 1.

In `BackLink.test.tsx`:
- `it("names the recorded origin")`
- `it("falls back when nothing is recorded")`

- [ ] **Step 2: Run and see them fail**

Run: `npx vitest run src/lib/__tests__/backNav.test.ts src/components/nav`
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement** `stored.ts`, `backNav.ts`, `NavRecorder.tsx` and `BackLink.tsx`, and mount the recorder.

- [ ] **Step 4: Run tests, lint and types**

Run: `npx vitest run src/lib src/components/nav "src/app/(app)" && npx eslint src/lib src/components/nav "src/app/(app)/layout.tsx" && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit** `feat(nav): Back returns where you came from`

### Task 4: The side list shell

**Files:**
- Create: `frontend/src/components/nav/SideListLayout.tsx`
- Test: `frontend/src/components/nav/__tests__/SideListLayout.test.tsx`

**Interfaces:**
- Produces:
  `SideListLayout({ sideLabel, side, hideSide, children }: { sideLabel: string; side: React.ReactNode; hideSide?: boolean; children: React.ReactNode })`.
  - **From `md` up:** a grid `md:grid-cols-[16rem_minmax(0,1fr)]` with `<aside aria-label={sideLabel} className="card hidden p-3 md:block …">`.
  - **Below `md`:** a button `{sideLabel}` (`md:hidden`) opens a panel (`role="dialog"`, `aria-label={sideLabel}`)
    with a `Close` button. A click on any link inside the panel closes it.
  - **`hideSide`:** drops the aside and the button, so the content takes the full width.

- [ ] **Step 1: Write the failing tests:**
- `it("shows the list beside the content")`
- `it("opens the list as a panel from its button and closes it when a link is picked")`
- `it("hides the list while hideSide")`

- [ ] **Step 2: Run and see them fail.** `npx vitest run src/components/nav/__tests__/SideListLayout.test.tsx`.
  Expected: FAIL.

- [ ] **Step 3: Implement `SideListLayout`.** Follow the app layout's menu overlay for the panel: a backdrop button
  `Close` and an `aside`.

- [ ] **Step 4: Run tests and lint.** Same command, plus `npx eslint src/components/nav`. Expected: PASS.

- [ ] **Step 5: Commit** `feat(nav): a side list beside the content, behind a button on phones`

### Task 5: The Knowledge Base reader

**Files:**
- Modify:
  - `frontend/src/lib/kb.ts`: helpers.
  - `frontend/src/components/kb/FolderTree.tsx`: documents in the tree; open state.
  - `frontend/src/app/(app)/kb/[spaceId]/page.tsx` and `frontend/src/app/(app)/kb/doc/[docId]/page.tsx`: use the
    reader, and drop their own "Knowledge Base" link lines.
  - `frontend/src/app/(app)/kb/search/page.tsx`: trail, Back, and drop its link line.
- Create: `frontend/src/components/kb/KbReader.tsx` (with `KbSearchBox`), `frontend/src/components/kb/DocPager.tsx`
- Test:
  - `frontend/src/components/kb/__tests__/FolderTree.test.tsx` (update);
  - `frontend/src/components/kb/__tests__/KbReader.test.tsx` (new);
  - `frontend/src/lib/__tests__/kb.test.ts` (new).

**Interfaces:**
- Consumes: `useTrail` (Task 1); `BackLink`, `useStoredState` (Task 3); `SideListLayout` (Task 4).
- Produces:
  - `kbSiblings(documents: KbTreeDoc[], docId: string): { prev: KbTreeDoc | null; next: KbTreeDoc | null }`. It
    looks at the same `folder_id`, with null meaning the top level, in `DocList`'s order (`title.localeCompare`).
  - `folderChain(folders: KbFolder[], folderId: string | null): KbFolder[]`: from the root down to `folderId`.
    Unknown IDs give `[]`.
  - `FolderTree` props gain `currentDocId?: string | null`. The tree lists each folder's subfolders, then its
    documents. Top-level documents come after the top-level folders.
    - A document is a `treeitem` holding a `Link` to `/kb/doc/<id>`. The current one has `aria-current="page"` and
      the selected styling.
    - Open folders: the set of open folder IDs lives in `useStoredState("kb.open.<spaceId>", [], "local")`. IDs that
      are no longer folders are ignored (Review Focus 3).
    - A folder never opened starts closed.
    - On arrival, and whenever `selected` or `currentDocId` changes, the folders on the path to it (from
      `folderChain`) are added to the set. The item is then scrolled into view with `scrollIntoView?.({ block: "nearest" })`.
    - Clicking a folder's name selects it and opens it. The chevron toggles it.
  - `KbReader({ spaceId, folderId, docId, docTitle, editing, children })`:
    - **Trail:** Knowledge Base (`/kb`) › space name (`/kb/<space>`) › each folder in `folderChain`
      (`/kb/<space>?folder=<id>`) › `docTitle`. The last crumb never links.
    - **Row:** `BackLink` with area `kb-read` and a fallback, then `KbSearchBox`. The fallback is:
      - for a document, its folder (name and `?folder=` link), or the space at the top level;
      - for a folder, its parent folder, or the space;
      - for the space's top level, `{ href: "/kb", label: "Knowledge Base" }`.
    - **Below the row:** `SideListLayout` with `sideLabel="Files"`, `side` = `FolderTree`, and `hideSide={editing}`.
  - `KbSearchBox({ spaceId })`: submits to `/kb/search?q=<text>&space=<spaceId>`.
  - `DocPager({ documents, docId })`: `nav` named `Folder`, with `← {prev.title}` and `{next.title} →` links.
- Page changes:
  - **Space page:** picking a folder uses `router.push`.
  - **Search page:**
    - trail `[{ label: "Knowledge Base", href: "/kb" }, { label: "Search" }]`, with `backName` `` `results for "${q}"` `` when there is a query;
    - `BackLink` with area `kb-search` and fallback `{ href: "/kb", label: "Knowledge Base" }`.

- [ ] **Step 1: Write the failing tests:**
- **`kb.test.ts`:** `kbSiblings` covers the middle, the first, the last, and the top level. `folderChain` covers a
  nested folder, the top level and an unknown ID.
- **`FolderTree.test.tsx`** (update the existing tests to the new open state, then add):
  - `it("lists documents under their folders and marks the current one")`
  - `it("opens the path to the current document and remembers folders opened by hand")`: check localStorage
    `kb.open.s1`.
  - `it("ignores remembered folders that no longer exist")`
  - `it("works when storage throws")`
- **`KbReader.test.tsx`:**
  - `it("a document shows the tree, its trail, the pager and Back to its folder when opened directly")`: no origin,
    so the link reads `← Back to Guides` and points to `/kb/s1?folder=f1`. This is Review Focus 2.
  - `it("the search box searches this space")`
  - `it("the tree folds away while editing")`

- [ ] **Step 2: Run and see them fail**

Run: `npx vitest run src/lib/__tests__/kb.test.ts src/components/kb`
Expected: FAIL.

- [ ] **Step 3: Implement** the helpers, `FolderTree`, `KbReader`, `DocPager` and the three page changes.
  - **Document page:** wraps its content in `KbReader` once the document loads, with
    `spaceId={d.space.id}`, `folderId={d.folder_id}`, `docId={d.id}` and `docTitle={d.title}`.
    `DocPager` goes below `DocView`, using the tree from `useKbTree(d.space.id)`.
  - **Space page:** wraps the folder view in `KbReader`.

- [ ] **Step 4: Run tests, lint and types**

Run: `npx vitest run src && npx eslint src && npx tsc --noEmit`
Expected: PASS. Update `DocPage.test.tsx` and `titles.test.tsx` fixtures only where the tree request needs a stub.
Leave their assertions as they are.

- [ ] **Step 5: Commit** `feat(kb): the folder tree stays beside what you read`

### Task 6: The Memory reader

**Files:**
- Create: `frontend/src/components/memory/EntitySidebar.tsx`
- Modify:
  - `frontend/src/app/(app)/memory/entity/[id]/page.tsx`
  - `frontend/src/components/memory/EntityList.tsx`: the filter is kept.
  - `frontend/src/components/memory/AskMemory.tsx`: the last Ask is kept.
- Test: `frontend/src/components/memory/__tests__/Memory.test.tsx` (add), `frontend/src/components/memory/__tests__/EntitySidebar.test.tsx` (new)

**Interfaces:**
- Consumes: `useTrail` (Task 1); `BackLink`, `useStoredState` (Task 3); `SideListLayout` (Task 4).
- Produces:
  - `EntitySidebar({ currentId }: { currentId: string })`: `useMemEntities()` grouped by `ENTITY_GROUPS`, each
    entry with its count. The filter uses `useStoredState("memory.filter", "", "session")`. The current entry has
    `aria-current="page"` and is scrolled into view.
  - The entity page:
    - trail Memory (`/memory`) › the group label (plain text) › the entity name;
    - a row with `BackLink` (area `memory-read`, fallback `{ href: "/memory", label: "Memory" }`);
    - its content inside `SideListLayout` with `sideLabel="Entities"`.
  - `EntityList`'s filter uses `memory.filter`.
  - `AskMemory` keeps `{ question, project, answer }` in `useStoredState("memory.ask", …, "session")`.

- [ ] **Step 1: Write the failing tests:**
- `it("the entity list sits beside the entity, grouped, with the current one marked")`
- `it("the filter is shared with the Memory page and kept for the tab")`
- `it("AskMemory shows the last answer again after a remount")`
- `it("works when storage throws")`

- [ ] **Step 2: Run and see them fail.** `npx vitest run src/components/memory`. Expected: FAIL.

- [ ] **Step 3: Implement** the sidebar, the entity page and the kept state.

- [ ] **Step 4: Run tests, lint and types.** `npx vitest run src && npx eslint src && npx tsc --noEmit`. Expected: PASS.

- [ ] **Step 5: Commit** `feat(memory): the entity list stays beside the entity`

### Task 7: End to end

**Files:**
- Modify: `frontend/e2e/kb.spec.ts`, `frontend/e2e/memory.spec.ts`. Fix existing steps that the new layout makes
  ambiguous, for example a document title now also shown in the tree, by scoping them to the content.
- Test: the two specs above, then the whole Playwright suite.

- [ ] **Step 1: Add the tests:**
- **`kb.spec.ts`: `test("knowledge base: read a folder file by file and come back")`**
  1. Seed one space with a folder `Guides` holding `Alpha`, `Beta` and `Gamma`.
  2. Search `Beta` and open the result.
  3. Click `Gamma` in the tree, then `← Beta` in the pager. The tree stays visible throughout.
  4. The top bar reads `Knowledge Base` › space › `Guides` › `Beta`.
  5. `← Back to results for "Beta"` returns to `/kb/search?q=Beta`.
  6. Open `Alpha` directly by URL: Back reads `← Back to Guides`.
- **`memory.spec.ts`: `test("memory: hop between entities and come back")`**
  1. On `/memory`, type a filter, then open an entity.
  2. Pick another entity in the list. The URL changes and the list stays.
  3. `← Back to Memory` returns to `/memory`, and the filter is still filled in.

- [ ] **Step 2: Run the whole suite** with the scratchpad `e2e-run.sh`, writing the log to
  `.superpowers/sdd/2026-11-01-plan-22-kb-memory-navigation/e2e.txt` (create that folder first).
  Expected: every test passes.

- [ ] **Step 3: Commit** `test(e2e): getting around the Knowledge Base and Memory`
