# MC-173: A2UI rich replies, a read-only card in a task's or chat's thread

This design goes with mockup **v1** ("Cards in the thread v1: a chat, a task, where a card can't be drawn, and the agent's side").

## Goal

An agent can show a result as a card in the Activity thread of its task or chat, next to its Markdown reply: stat tiles, tabs, and lists with links to tasks. Every card also has a title and a short text, which stand in for it wherever a card can't be drawn.

## Decisions

| Decision | Chosen | Why, and what was rejected |
| --- | --- | --- |
| Button that opens a link | **No button** (your answer). | A card's `Text` is drawn by our `Markdown` component, so Markdown links already work, and `TaskLink` covers tasks. Rejected: a link button for in-app pages only, and one for any https link. The catalog still has no `Button` and no `openUrl`. |
| Storage | **A card is its own thread item**, in a table of its own (your answer, approach A). | Title and text are first-class fields, so prompts, search and notifications read them without the surface. Rejected: an event holding the surface (up to 16 KB of JSON would go wherever events go), and a fenced block in the reply (never validated, cut at 4,000 characters). |
| Task links | **A snapshot**: the key and the words the agent wrote (approved with the mockup). | It matches the tiles, which are also a snapshot. Rejected: looking up the live title and column, which needs a lookup for each card and a rule for tasks the reader can't see. |
| Who may show a card | An agent's run on its own task or chat, in the roles that may call `ask_human`. A personal token on a task its owner can edit. | Approved with the mockup. Reviewers judge what is there, and cron runs have no task (their panel is the other MC-172 follow-up). |
| Catalog | The same catalog file and id (`urn:megoocolab:a2ui:catalog:v1`), with four new entries. Forms and cards each have their own allowed set. | Adding entries doesn't change stored forms. Forms keep exactly the components they have today. |
| Guide | A new tool `get_card_guide`. | As with `get_form_guide`, the catalog stays out of every session's tool descriptions. |
| Card text on the page | The title is the card's heading. The text shows only where the card can't be drawn. | Approved with the mockup. |

## Architecture

### Step 1 settles three points in code

The A2UI packages aren't installed in the design checkout, so these could not be confirmed by reading. The first build step confirms them and records the result with `record_decision`.

1. `a2ui-core` 0.7.0 validates `Tabs`, a `List` whose `children` is a template (`{componentId, path}`), and our own two components defined in `catalog.json`.
2. `@a2ui/web_core/v1_0` 0.15.0 exports `TabsApi` and `ListApi`. If it doesn't, we define both as our own component APIs with zod, the way `StatTile` and `TaskLink` are defined.
3. The React renderer expands a template into our components, with paths relative to each row.

If point 1 or 3 fails for templates, `List` takes only a fixed list of children and the guide says so. Nothing else in this design changes.

### Backend

- **`backend/app/a2ui/catalog.json`** gets four entries:
  - `Tabs` and `List`, with the properties of A2UI's basic catalog.
  - `StatTile`: `label`, `value`, `caption?`, `tone?` (`neutral`, `good`, `warning`, `bad`).
  - `TaskLink`: `task` (a key such as `MC-181`) and `label?`.
- **`backend/app/a2ui/service.py`**:
  - `FORM_COMPONENTS` (the ten of today) and `CARD_COMPONENTS` (`Column`, `Row`, `Card`, `Divider`, `Text`, `Tabs`, `List`, `StatTile`, `TaskLink`).
  - `clean_form` also refuses a component outside `FORM_COMPONENTS` with `invalid_form`.
  - `clean_card(card)` is new. It takes `{components, data?}`, checks the card limits, wraps it with a surface id `card-<12 hex>`, and validates it. It raises `CardError`, shaped like `FormError`.
  - `guide()` becomes `form_guide()` and `card_guide()`. Each returns its own instructions, the catalog cut down to its allowed components, and an example.
  - New files `card_guide.md` and `card_example.json`.
- **`backend/app/tasks/models.py`**: the new model `TaskCard` (see Data).
- **`backend/app/tasks/cards.py`** (new): `show(db, task, run, user, title, text, card)` cleans the three inputs, checks the count limits, stores the row, publishes `task.updated` and touches the chat when the task is a chat round.
- **`backend/app/tasks/activity.py`**: a fourth item type, `card`. `_shown`, `count_after` and `activity_items` include `TaskCard` rows the way they include questions.
- **`backend/app/mcp_server/workflow_tools.py`**: the tools `show_card` and `get_card_guide`, and a `TOOL_ROLES["show_card"]` entry equal to `ask_human`'s.
  - Run token: `_task(..., write=True)`, then `live_run`.
  - Personal token: `get_task_for(..., write=True)`, the rule `comment_on_task` uses. It doesn't start or touch a workflow.
- **Where the title and text are read:**
  - `workflow/context.py`: `_thread` keeps `card` items, and `_item_text` prints `[card by <name> at …]`, then the title, then the text. It is inside the untrusted thread block.
  - `workflow/freestyle.py`: `conversation_so_far` adds a turn's cards (title and text) to that turn's reply. `_notify_replied` appends `Card: <title>. <text>` for each card of the turn to the body, within its 500 characters. This is what Telegram, push and email carry.
  - `mcp_server/server.py`: `get_task` returns card items without `surface`.
  - `search/documents.py`: a task's card titles and texts are indexed with its comments. `search/capture.py` marks the task for reindexing when a card is stored. Chat rounds stay unsearched, as today.
- **Methodology texts:** `freestyle.md` and `finish.md` get one line on `show_card` and one rule: use a card only when a result reads better as tiles, tabs or a list of task links than as Markdown, and still reply in text.

### Frontend

- **`components/a2ui/FormSurface.tsx` is renamed `Surface.tsx`** (component `Surface`), because it now draws forms and cards. It stays the only file that imports `@a2ui/*`. It gets a `fallback` prop, shown when loading or drawing fails; without it the form message of today is shown. `QuestionCard` imports the new name.
- **`components/a2ui/catalog.tsx`** gets four plain components and their `COMPONENT_PROPS` entries:
  - `Tabs`: underline tabs with the look and keys of `ui/Tabs`, with the open tab kept in local state (not in the address). Hidden panels stay mounted.
  - `List`: rows with a line between them. It scrolls inside the card past about 15 rem.
  - `StatTile`: the look of the Dashboard's `Tile` (a mono value, a label, a caption), coloured by `tone`.
  - `TaskLink`: the key as a link to `/projects/<KEY>/board?task=<key>`, the format the thread already uses, followed by the label. A value that isn't a task key is drawn as plain text.
- **`components/task/ThreadCard.tsx`** (new): the card box with the title as its heading and `<Surface message readOnly fallback=… />` below. The fallback is the text and "This card couldn't be drawn. This is its text."
- **`components/task/ActivityThread.tsx`**: a `card` item is a row with the dot, "<name> showed a card" and the time, then `ThreadCard` at full width, like a reply box. It works unchanged in chats, which draw the same component through `RoundSections`.
- **`lib/types.ts`**: `ActivityCard`, and `FormMessage` renamed `SurfaceMessage`. `lib/api-types.ts` is regenerated.

A card between two pieces of a reply splits the reply in two, as other items already do. That is the intended order: text, card, text.

## Data and interfaces

- **Migration:** the table `task_cards`.
  - `id`
  - `task_id` (FK to tasks, cascade, indexed)
  - `run_id` (FK to agent_runs, set null)
  - `agent_id` (FK to agents, set null)
  - `user_id` (FK to users, set null; set for a personal token)
  - `title` varchar(120)
  - `text` text
  - `surface` JSONB (the `createSurface` message)
  - `created_at`
- **MCP `show_card(key, title, text, card)`:** `card` is `{components: [...], data?: {...}}`. It returns `{"card_id": "<uuid>"}`. The agent keeps working; it doesn't end the turn.
- **MCP `get_card_guide()`:** returns `{instructions_md, catalog, example}`.
- **Activity item `card`:** `{type: "card", id, at, actor, card: {id, title, text, surface, agent: {id, name} | null}}`. `actor` is the person for a personal token and null for a run.
- **Limits:** title 1 to 120 characters, text 1 to 500, 16 KB of card JSON, 60 components, 6 tabs in one `Tabs`, 50 items in any array of `data`, 3 cards in one run, 100 on one task.

## Error handling and edge cases

- **Doesn't match the catalog:** `invalid_card` with up to 10 `path: message` lines. Nothing is stored, and the agent can correct it and call again.
- **An input component:** `card_with_inputs`. A button, image or media component isn't in the catalog, so it is `invalid_card`.
- **A literal `task` on a `TaskLink` that isn't a task key:** `invalid_card`. A value bound to `data` is checked only when drawn.
- **Over a size limit:** `too_large`. **Over a count limit:** `too_many_cards`. **Empty title or text:** `invalid_card`.
- **Wrong session:** `not_allowed_in_role` (a reviewer or a cron run), `wrong_task` (another task's key), `run_not_running`.
- **The task link is not checked against the board.** A reader who can't see the task gets the usual not-found page.
- **The renderer fails to load or throws:** the card shows its title and text with the note above.
- **Read-only views and ended chats:** a card looks the same; it has no state to lock.
- **A deleted task** takes its cards with it. A deleted agent or run leaves the card, shown as "Agent".
- **The Dashboard's Recent Activity** is unchanged, because a card is not an event.

## Testing

- **Backend (pytest):**
  - Validation: a fixture file `cards.json` of valid and invalid cards, covering each new component, a template list, an input, a button, a bad tone, a bad literal task key and each limit. Forms still refuse the four new components.
  - `cards.show`: stores the row, publishes, touches the chat, and refuses over each count limit.
  - Tools: `show_card` for each allowed role, for a refused role, for a cron run and for a personal token; `get_card_guide` lists exactly the card components, and `get_form_guide` exactly the form ones.
  - Activity: the `card` item, its paging and `count_after`.
  - Text: `_item_text`, `conversation_so_far`, the notification body, `get_task` without `surface`, and the search document.
  - Migration: down and up again.
- **Frontend (Vitest):**
  - `Surface` draws every valid card fixture, switches tabs, expands a template list, and shows the fallback when drawing fails.
  - `catalog` parity with `catalog.json` for the four new entries.
  - `ActivityThread` draws a `card` item with its title, and a `TaskLink` points at the board address.
  - `QuestionCard` still passes under the renamed import.
- **Browser (Playwright):** an agent shows a card in a chat; the thread draws the tiles, a tab is switched, and a task link opens the task.

## Out of scope

- A button of any kind, `openUrl`, images, icons and media.
- Live task links (current title or column).
- Editing, deleting or updating a card, and streaming one.
- Cards from cron runs (the other MC-172 follow-up) and from reviewers.
- The four new components inside forms.
- Cards in the memory's sources, and searching chats.
- Charts.
