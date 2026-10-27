# Global search with Meilisearch — design

**Date:** 2026-10-27
**Builds on:** `docs/brd.md` and merged Plans 1–8. Requirements this touches: KB-search (the Knowledge Base search page
stays), NFR-2 (no source code on the server), NFR-4 (changes visible within about 2 s), and §4 (one docker compose
install).

## 1. Why

MegooColab has no single place to find things. Today:
- the Knowledge Base has its own search page, with full-text and meaning-based matching;
- tasks can be filtered by words in their title only;
- people are found by name in pickers;
- memory entities are filtered by name.

The owner wants **one search box that finds anything**, with **advanced filters**. They want it built on
**Meilisearch from the start**, so search stays fast as the data grows rather than being reworked once it gets
slow.

Success: anyone presses Ctrl+K anywhere, starts typing, and within a moment sees the task, document, project,
person or answer they meant, even with a typo. When they need to dig, a full results page narrows by project,
status, assignee and so on. They never see anything they couldn't already open.

## 2. Goals, non-goals, anti-goals

**Goals**
- A **quick search box** (Ctrl+K / Cmd+K, plus a search button in the header) that searches as you type, forgives
  typos, and groups results by kind.
- A **full results page** ("See all results") with filter controls down the side. The owner picked option B in the
  mockups, which are kept at [assets/2026-10-27-global-search-mockup.html](assets/2026-10-27-global-search-mockup.html).
  It is a wireframe: the layout is binding, the styling follows the app.
- On the results page, an optional **"Also match by meaning"** switch for documents, available only when an
  embeddings provider is configured.
- Meilisearch is a **required** service of every install (the owner's decision).

**Non-goals**
- Agents using this search. It is for people only (the owner's decision: "I don't want to confuse the agents").
  The agents' MCP tools (`kb_search`, `search_memory`, `find_answer`) are unchanged.
- Replacing the Knowledge Base search page. It keeps its own full-text and meaning-based search.
- Searching memory conclusions, agent decisions, mockups, notifications or test runs. These can be added later,
  so the design must make adding a kind cheap.
- A database fallback when Meilisearch is down.
- Synonym lists, saved searches and search analytics.

**Anti-goals** (failure even if it works)
- **A result, a count, a snippet or a filter value from something the person cannot open.** A private project's
  task must not appear, and must not change "37 results" or a facet count either.
- Search becoming a way around a revoked permission. When someone leaves a team, that team's projects stop
  appearing for them as soon as the change is saved.
- Source code reaching the index (NFR-2). Only text already stored on the platform is indexed.
- The quick box feeling slow: results should arrive while typing, with no visible wait.
- Search being down taking anything else down.

## 3. What can be found

Every search covers six kinds:

| Kind | What is searchable | Who can see it (same rule as opening it today) |
|---|---|---|
| **Tasks** | key (exact, no typos), title, description, comments | members of the task's project (its teams), and admins |
| **Documents** | Knowledge Base pages (title and body), including the approved designs, plans and reviews filed there | anyone who can read the page's space |
| **Projects** | key, name, description | project members and admins |
| **Teams** | name, description | every signed-in user (today any signed-in user can list and open every team) |
| **People** | name and email of active users | every signed-in user (as in today's pickers) |
| **Agents** | name, owner's name | every signed-in user (today a team's page shows its members' agents to anyone) |
| **Questions** | A2A questions and their answers | the same rule as today's questions page (`readable_by`) |

"Same rule as opening it today" means the app as it behaves now, not a stricter rule. Tightening who may see teams
and agents is a separate question that search doesn't settle. (My call.)

**Where a result takes you:**
- **Tasks:** the task (`/projects/<KEY>/board?task=<KEY>-<n>`).
- **Documents:** `/kb/doc/<id>`.
- **Projects:** the project board.
- **Teams:** `/teams/<id>`.
- **Questions:** `/questions/<id>`.
- **People and agents:** there is no page for either, so opening one shows a small card in place. For a person:
  name, email and their teams, each linking to its team page. For an agent: name, owner, status, and only the
  projects it is bound to that the viewer can see. The card is built from what search already returns: no new
  pages and no new endpoints beyond search. (My call.)

Comments are searched as part of their task. A hit in a comment shows the task, with the comment's matching
words as the snippet. (My call, so results stay "things you open" rather than a flood of comments.)

## 4. How it behaves

### Quick box
- **Opening it:** Ctrl+K (Cmd+K on macOS) from any page, or a search button in the header.
- **Searching:** results update as you type, grouped by kind in the order of the table above, with at most 5 per
  group (my call).
- **Matching:**
  - Each result shows its title, a short line of context and the matching words highlighted.
  - Typos are forgiven the Meilisearch way: words of 5 or more letters allow one typo, 9 or more allow two, and
    shorter words must match exactly.
  - The last word typed also matches as a prefix ("paym" finds "payment").
  - Task and project keys only match exactly: `PAY-42` never returns `PAY-24`.
- **Keyboard:** arrow keys move, Enter opens, Esc closes.
- **See all results:** the last row is "See all N results", which opens the full page with the same query.
- **Empty box:** shows nothing until you type (my call; recent items are a later addition).

### Full results page (`/search?q=…`)
- **Results:** the query box at the top, and below it one list across all kinds, sorted by relevance. A
  "Newest first" sort is offered too.
- **Filters** down the side, each with counts that only include what the person can see:
  - **Kind:** tasks, documents, projects, teams, people, agents, questions.
  - **Project.**
  - **Status:** the task's board column category (to do, in progress, review, done).
  - **Assignee:** a person or an agent.
  - **Task type and labels.**
  - **Last updated:** last 7 days, last 30 days, last year, any time.
- **Filters that don't apply:** filters only fit some kinds. Picking "Status: done" narrows to tasks, and the page
  says so.
- **Shareable:** the query and the filters live in the URL, so a search can be shared or bookmarked; the person
  who opens it still sees only what they are allowed to.
- **Paging:** 20 results per page, with "Load more".
- **"Also match by meaning":**
  - It appears only when an embeddings provider is configured.
  - When on, document results also include pages that match by meaning, using the same provider and
    embeddings as the Knowledge Base search.
  - The other kinds stay word-matched.

### When search is down
The box and the page say "Search is unavailable right now" and everything else keeps working. Admins see the
search service's health in the admin area.

## 5. Keeping the index current

- **Freshness:** creating, editing, moving, commenting, renaming, deleting and permission changes reach the index
  within about 2 seconds (NFR-4), through the existing background job queue, so a slow or restarting Meilisearch
  never slows a save.
- **Recovery:** a full rebuild can be started from the admin area and runs on its own when the index is empty,
  for example on a fresh install or after Meilisearch's data was lost. It rebuilds everything from the database,
  which stays the source of truth.
- **Permissions:**
  - They are stored on each indexed item as the ids that may read it: project, team or space.
  - Every search asks Meilisearch to filter by the ids the person can read, worked out at search time from the
    database.
  - So a revoked membership takes effect on the next search, with no reindexing.
  - Admins match everything they can open today.
- **Security:**
  - The browser never talks to Meilisearch directly: searches go through the MegooColab backend, which adds the
    permission filter.
  - Meilisearch's master key lives only in the backend and worker configuration.

## 6. Constraints

- **Install:**
  - Meilisearch is a new service in `deploy/docker-compose.yml` with its own volume and a generated master key
    in `.env`.
  - It is reachable only on the internal network.
  - Use a pinned, current stable version.
  - The install guide (`docs/install.md`) and the backup and restore section are updated: the index can always be
    rebuilt, so backups don't need it.
- **Dependencies:** use the official Python client for Meilisearch in the backend. No new frontend search
  library.
- **Language:** the UI copy is plain English like the rest of the app.
- **Tests and e2e:** use the same Meilisearch in tests (a test container or the dev compose), not a mock, for the
  permission and typo cases.

## 7. Calls I made (the owner didn't decide these)

1. The kinds and fields in §3, including comments being searched as part of their task.
2. Keys only match exactly.
3. At most 5 results per kind in the quick box; nothing is shown before you type.
4. Permissions are checked at search time from the database through stored reader ids, not by reindexing on
   every permission change.
5. Searches always go through the backend; the browser never holds a Meilisearch key.
6. There's a "Newest first" sort, the filters are the ones listed in §4, and search state lives in the URL.
7. A rebuild runs on its own when the index is empty, and admins can also start one.
8. The "Also match by meaning" switch covers documents only and reuses the Knowledge Base's embeddings provider.
9. Teams and agents follow today's visibility, which means every signed-in user can see them, rather than a stricter
   rule.
10. People and agents open as a small card in place, because there are no pages for them.

## 8. Left to the builder

- Index layout: one index for everything or one per kind, plus field names and ranking rules (keep the
  defaults unless a test shows a need).
- The exact typo-tolerance numbers, if the defaults misbehave on short words.
- How the meaning switch merges document results, whether through Meilisearch's hybrid search with the
  provider's embeddings or by blending with the existing Knowledge Base search.
- The visual layout beyond the mockup the owner chose.
