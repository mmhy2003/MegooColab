# Getting around the Knowledge Base and Memory — design

Owner-approved direction: option B for both pages (mockup
`.superpowers/brainstorm/233-1793538929/content/kb-memory-nav.html`), and the top bar's trail fixed across the whole app.

## Why

The owner reads the Knowledge Base folder by folder. Today, opening a document and wanting the next one means going
back to the Knowledge Base front page, reopening the space and finding the folder again:

- a document's only way back is "Knowledge Base / <space>", which opens the space at its **top level**, not the folder;
- picking a folder uses `router.replace`, so the browser's Back skips every folder and leaves the space;
- the top bar's trail is built from the URL, so it reads `kb / doc / 3f9a…` or `memory / entity / 81c2…`, and the
  middle crumbs (`/kb/doc`, `/memory/entity`) only redirect to the section's front page;
- a document opened from search results has no way back to them; Memory's filter and its last Ask answer are gone
  when you come back.

Memory has the same shape: an entity page links only to "Memory", and moving to another entity means going back to
the list.

Success: reading the next file in a folder, or the next entity, is one click, and the way back always leads where the
person came from.

## Goals

1. **Knowledge Base: the tree stays beside what you read.** A space and a document share one layout: the space's tree
   on the left, the open folder or document on the right.
2. **Memory: the entity list stays beside the entity.**
3. **A Back button that returns where you came from**, named for it.
4. **The top bar's trail shows names, across the whole app**, and every crumb opens a real page.
5. **Nothing you set up is forgotten** when you leave and come back: open folders, the selected folder, filters, the
   search text, the last Ask answer.

## Non-goals

- No change to what the Knowledge Base or Memory store, or to search ranking.
- No "Recently viewed" list (offered, not chosen).
- No redesign of the Memory front page (Ask, products, the entity grid stay as they are) or of the Knowledge Base
  front page beyond the search box it already has.

## Anti-goals

- A tree that is unusable in a big space: "Designs & Plans" holds a folder per task and can have hundreds.
- A Back button that leads somewhere surprising (the top of the space, the front page) when the person came from
  somewhere specific.
- Two different trails on one screen that disagree.
- Raw IDs anywhere in the trail, even for a moment while names load.

## Knowledge Base

### One layout for a space and a document

`/kb/<space>` (with `?folder=`) and `/kb/doc/<id>` both show:

- **Left: the space's tree**, folders **and** documents, sorted by name as today (folders first, then documents).
  - The open folder or document is highlighted.
  - On arrival, the folders on the path to the open item are expanded and scrolled into view. Other folders keep
    whatever open/closed state the person left them in; a folder never opened starts closed.
  - Clicking a document opens it in the right pane. Clicking a folder opens its folder view in the right pane and
    expands it.
  - Folder actions writers have today (new folder, rename, delete) stay in the tree.
  - **Big folders.** A closed folder renders none of its contents, so hundreds of task folders under "Designs &
    Plans" stay one closed row each. Only the path to the open item opens by itself. No virtualization or cap
    *(my call)*.
- **Right, a folder:** what the space page shows today: the folder's documents (title, revision, date) and
  **New document**.
- **Right, a document:** the document as today (header, Edit / Move / Delete, Document and History tabs, body, Linked
  from), plus **Previous / Next** at the bottom: the documents before and after it in the same folder, in the tree's
  order, each named. There is no Previous on the first document and no Next on the last. A document at the space's
  top level steps through the other top-level documents.
- **While editing** a document, the tree folds away to give the editor the width; it comes back on save or cancel.
- **On a phone** (below the `md` breakpoint), the tree is behind a **Files** button that opens it as a panel; picking
  a file closes the panel.

Data: the tree endpoint the space page uses today (`/api/kb/spaces/{id}/tree`, folders and documents) already has
everything the tree needs, and a document carries its `space`, `folder_id` and `path`. The builder decides whether the
tree's data is shared between the two routes (a common layout) or fetched on each.

### The row above the content

On every Knowledge Base page except the front page (which already has search):

- **← Back** (see "Back" below);
- a **search box** that opens the Knowledge Base search for its text, limited to this space by default with the
  existing "All spaces" choice on the results page.

The in-page "Knowledge Base" link lines and the document page's own "Knowledge Base / <space>" line go: the top bar's
trail replaces them (see "The top bar's trail").

### Browser history

Opening a folder adds a history entry (`router.push`, not `replace`), so the browser's Back steps back through folders
and documents one at a time.

## Memory

An entity page (`/memory/entity/<id>`) shows:

- **Left: the entity list**, grouped as on the Memory page (Projects, Teams, People, Agents, Products…), each with its
  conclusion count, and the same filter box. The open entity is highlighted and scrolled into view.
  - The list comes from the same unpaginated `/api/memory/entities` the Memory page uses. It is the same data and
    the same scale as the grid there.
- **Right:** the entity as today (summary cards, conclusions, Delete product for managers).
- **On a phone**, the list is behind an **Entities** button, as the Knowledge Base tree is.
- The row above the content holds **← Back**.

The Memory front page keeps its layout. Its filter text and the last Ask question and answer are kept when the person
leaves and comes back (same tab).

## Back

A **← Back** button on Knowledge Base pages (spaces, documents, search results) and Memory entity pages.

- It returns to the page the person came from **before** they started moving around inside the tree or list.
  Moving between documents and folders with the tree or Previous / Next, or between entities with the list, does not
  change where Back leads: the browser's own Back steps through those (owner's pain point: getting back to where they
  were, not stepping through every file). *(My call; the owner can change it.)*
- Its label names the place: "← Back to results for 'retry'", "← Back to PAY-12 (task)", "← Back to Payments
  (memory)", "← Back to the answer" (an Ask answer), "← Back to Designs & Plans".
- When there is no such page (a link opened in a new tab, a notification, a bookmark), Back leads one level up: a
  document to its folder, a folder to its parent folder, a space's top level to the Knowledge Base, an entity to
  Memory.
- Returning restores the place as it was: the results page with its query and space filter, the Memory page with its
  filter and Ask answer, the folder with its tree state.

Settled details *(my calls, from the builder check)*:

- **The reading area.** Knowledge Base spaces and documents form one reading area; Memory entity pages form another.
  A move *within* a reading area (tree, Previous / Next, a "Linked from" link, a link to a document in another space,
  the entity list) keeps the origin. Arriving from anywhere else sets it: any page of the app, including the Knowledge
  Base front page, Knowledge Base search results and the Memory front page.
- **What is recorded:** the origin's URL and its label. The label is the last crumb of the origin page's trail (see
  "The top bar's trail"), so any page can be an origin with no special code. The search results page's last crumb
  reads "Results for 'retry'", which gives "← Back to results for 'retry'". The Memory front page gives "← Back to
  Memory", and returning restores its Ask answer.
- **Pressing Back** navigates to the origin URL (a normal push). It does not rewind the browser's history.
- **Storage** is the builder's call: a per-tab record of in-app navigation, or a parameter carried in the links. It
  must survive a reload. A link copied to someone else must not send them somewhere odd; falling back to "one level
  up" is fine.

## The top bar's trail (whole app)

The trail in the header stops being built from URL segments. It shows **names**, and every crumb opens a page that
exists.

- Each page states its trail. The builder adds a small hook alongside `usePageTitle` (`lib/title.ts`), for example
  `useTrail([...])`; the header renders the trail of the page shown, with the same "record over page" rule
  `usePageTitle` uses (a task open in the drawer names itself over the board under it).
- Static sections get readable names: `kb` → Knowledge Base, `admin` → Admin, `settings` → Settings, and so on,
  matching the sidebar's labels.
- Trails for the pages with IDs or keys, at least:

| Page | Trail |
|---|---|
| Knowledge Base space | Knowledge Base › *space* › *folder* › *subfolder* |
| Knowledge Base document | Knowledge Base › *space* › *folder…* › *document title* |
| Knowledge Base search | Knowledge Base › Search |
| Memory entity | Memory › *group (Projects, People…)* › *entity name* |
| Chat | Chats › *chat title* |
| Project pages | Projects › *project name* › Board / Backlog / Tasks / Chats / Reports / Settings |
| Task page | Projects › *project name* › *KEY-N* |
| Question | Questions › *question title* |
| Team | Teams › *team name* |
| Admin and Settings pages | Admin › *page*, Settings › *page* |

- A crumb with no page of its own is plain text, never a redirect. Examples: a group like "Projects" under Memory, or
  an intermediate segment.
- Every other crumb in the table above has a page today. The task page is `/projects/<key>/tasks/<n>`. Chats,
  Questions, Teams, Projects, Admin and Settings all have list pages.
- **Where names come from.** Each page already loads the record it shows. A trail needs nothing more than:
  - Knowledge Base: the tree (folder names and parents) and the document's space;
  - project pages: the project (`useProject(key)`);
  - Memory: the entity, whose kind gives the group.
  No new endpoint is expected.
- While a name is loading, the crumb shows a neutral placeholder (a short skeleton or "…"), never the ID.
- A long trail on a narrow screen collapses the middle crumbs into "…" (which opens the full trail), keeping the first
  and the last.
- The `kb/doc` and `memory/entity` redirect pages stop being linked; they can stay for old links.

## Remembering where you were

- **Knowledge Base:** each space's open/closed folders are remembered per browser; the selected folder is in the URL.
- **Search results:** the query and space are in the URL already; Back returns to them.
- **Memory:** the filter text and the last Ask question and answer are kept for the tab (they may be dropped when the tab
  closes).
- Whatever is kept must render correctly when storage is unavailable (private window): the page simply starts fresh.

## Constraints

- Frontend only, unless the builder finds a trail name that no existing endpoint provides; then the smallest
  read-only addition.
- Access is unchanged: the tree and entity list show only what the viewer can already see.
- Keyboard and screen readers: the tree keeps its `tree` / `treeitem` roles, the trail stays a `nav` named
  "Breadcrumb", and Back is a link or button with its full label.
- Works in light and dark themes and at phone width without horizontal scrolling.

## Left to the builder

- Component structure (a shared Knowledge Base layout, a shared "side list + content" shell for both sections).
- How the trail hook and the Back origin are implemented and stored.
- Exact styling, within the app's existing look (cards, `text-cyan-ink`, `border-line`).
- Unit tests for the trail, Back's fallback rules and Previous / Next; end-to-end tests for: reading three documents in
  a folder via the tree without leaving the page; search → document → Back to results; Memory entity → another entity
  via the list → Back to the Memory page with its filter kept.
