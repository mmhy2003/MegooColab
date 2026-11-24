# MC-173 implementation plan: a read-only card in a task's or chat's thread

## Goal
An agent calls `show_card(key, title, text, card)` and a validated, static A2UI surface (stat tiles, tabs, lists with task links) appears as its own item in the task's or chat's Activity thread; its title and text stand in for it everywhere a card can't be drawn.

## Architecture
- **Backend.** `backend/app/a2ui/catalog.json` gains `Tabs`, `List`, `StatTile`, `TaskLink`. `backend/app/a2ui/service.py` splits the catalog into `FORM_COMPONENTS` and `CARD_COMPONENTS`, adds `clean_card` / `CardError` and two guides. A new table `task_cards` (model `TaskCard` in `app/tasks/models.py`) is written by `app/tasks/cards.py:show`, called by the new MCP tool `show_card`. `app/tasks/activity.py` merges cards in as a fourth item type `card`; prompts (`workflow/context.py`, `workflow/freestyle.py`), notifications, `get_task` and search read only the title and text.
- **Frontend.** `components/a2ui/FormSurface.tsx` becomes `Surface.tsx` (still the only `@a2ui/*` importer) with a `fallback` prop and four new catalog components. `components/task/ThreadCard.tsx` draws a card; `ActivityThread.tsx` shows a `card` row (chats get it through `RoundSections`).

## File map
| File | Change |
| --- | --- |
| `backend/app/a2ui/catalog.json` | + `Tabs`, `List`, `StatTile`, `TaskLink`, and in `$defs.anyComponent.oneOf` |
| `backend/app/a2ui/service.py` | `FORM_COMPONENTS`, `CARD_COMPONENTS`, card limits, `CardError`, `clean_card`, `form_guide`, `card_guide`; `clean_form` refuses non-form components; `wrap(..., prefix=)` |
| `backend/app/a2ui/card_guide.md`, `card_example.json` | new: the card guide and example |
| `backend/tests/a2ui/fixtures/cards.json` | new: valid and invalid cards |
| `backend/tests/a2ui/test_catalog.py`, `test_service.py`, new `test_cards.py` | catalog and validation tests |
| `backend/app/tasks/models.py` | + `TaskCard` |
| `backend/migrations/versions/<rev>_task_cards.py` | new table `task_cards` |
| `backend/tests/tasks/test_task_cards_migration.py` | new |
| `backend/app/tasks/cards.py` | new: `show`, `of_runs`, limits |
| `backend/tests/tasks/test_cards.py` | new |
| `backend/app/tasks/activity.py` | `card` item in `_shown`, `count_after`, `activity_items`, `_message_of` |
| `backend/tests/tasks/test_activity.py` | + card item tests |
| `backend/app/mcp_server/workflow_tools.py` | `show_card`, `get_card_guide`, `TOOL_ROLES["show_card"]`; `get_form_guide` uses `form_guide()` |
| `backend/app/mcp_server/server.py` | `get_task` drops `card.surface` |
| `backend/tests/mcp/test_workflow_tools.py`, `test_mcp.py`, `backend/tests/crons/test_report.py` | tool tests |
| `backend/app/workflow/context.py` | `_thread` keeps cards, `_item_text` prints them |
| `backend/app/workflow/freestyle.py` | cards in `conversation_so_far` and `_notify_replied` |
| `backend/app/search/documents.py`, `capture.py` | card titles/texts indexed with comments; `TaskCard` marks its task |
| `backend/app/workflow/methodology_texts/defaults/freestyle.md`, `finish.md`, `methodology_history.py` | `show_card` lines and the Cards rule |
| `frontend/src/lib/types.ts`, `frontend/src/lib/api-types.ts` | `SurfaceMessage` (was `FormMessage`), `ActivityCard`; regenerated |
| `frontend/src/components/a2ui/Surface.tsx` (renamed from `FormSurface.tsx`) | `Surface`, `fallback`, four new components registered |
| `frontend/src/components/a2ui/catalog.tsx` | `Tabs`, `List`, `StatTile`, `TaskLink`, `TASK_KEY`, `COMPONENT_PROPS` |
| `frontend/src/components/a2ui/__tests__/Surface.test.tsx` (renamed), `catalog.test.ts` | tests |
| `frontend/src/components/workflow/QuestionCard.tsx` (+ test) | renamed import |
| `frontend/src/components/task/ThreadCard.tsx` | new |
| `frontend/src/components/task/ActivityThread.tsx` (+ test) | `card` row |
| `frontend/e2e/cards.spec.ts` | new browser test |

## Shared contracts (referenced by the steps)

### C1. New catalog entries (`catalog.json`)
`Tabs` and `List` are copied from the A2UI **v1.0 basic catalog bundled in the installed `a2ui-core` 0.7.0** (find it: `cd backend; uv run python -c "import a2ui.core, pathlib; print(pathlib.Path(a2ui.core.__file__).parent)"`, then `rg -l '"Tabs"' <that dir>`). Keep the basic catalog's description texts, its `$ref`s to `common_types.json#/$defs/...`, and set `weight` to `{"$ref": "#/$defs/Weight"}` as the other entries do. Expected shape (confirm against the file):
- `Tabs`: `tabs` (array of `{title: DynamicString, child: ComponentId}`, required), `weight`. Required: `component`, `tabs`.
- `List`: `children` (`ChildList`: ids or a `{componentId, path}` template), `direction` (`vertical`|`horizontal`, default `vertical`), `align` (`start`|`center`|`end`|`stretch`), `weight`. Required: `component`, `children`.

If the bundled definition has properties beyond these, keep them and list them in `COMPONENT_PROPS` too (record it with `record_decision`).

Our own two:
```json
"StatTile": {
  "type": "object",
  "description": "A headline number: a value with its label, an optional caption below, coloured by tone. A snapshot: it never updates.",
  "properties": {
    "component": {"const": "StatTile"},
    "label": {"$ref": "common_types.json#/$defs/DynamicString", "description": "What the value counts, e.g. 'Failed'."},
    "value": {"$ref": "common_types.json#/$defs/DynamicString", "description": "The value as text, e.g. '3' or '4m 12s'."},
    "caption": {"$ref": "common_types.json#/$defs/DynamicString", "description": "A short line under the label."},
    "tone": {"enum": ["neutral", "good", "warning", "bad"], "type": "string", "default": "neutral", "description": "The value's colour."},
    "weight": {"$ref": "#/$defs/Weight"}
  },
  "required": ["component", "label", "value"]
},
"TaskLink": {
  "type": "object",
  "description": "A link to a MegooColab task by its key, followed by a label. A snapshot: the label is the words you write, not the task's current title.",
  "properties": {
    "component": {"const": "TaskLink"},
    "task": {"$ref": "common_types.json#/$defs/DynamicString", "description": "A task key such as 'MC-181'."},
    "label": {"$ref": "common_types.json#/$defs/DynamicString", "description": "The words after the key."},
    "weight": {"$ref": "#/$defs/Weight"}
  },
  "required": ["component", "task"]
}
```
`COMPONENT_PROPS` (frontend) entries: `Tabs: ["tabs","weight"]`, `List: ["children","direction","align","weight"]`, `StatTile: ["label","value","caption","tone","weight"]`, `TaskLink: ["task","label","weight"]`.

### C2. `service.py` additions
```python
FORM_COMPONENTS = frozenset({"Column", "Row", "Card", "Divider", "Text", *INPUTS})
CARD_COMPONENTS = frozenset({"Column", "Row", "Card", "Divider", "Text", "Tabs", "List", "StatTile", "TaskLink"})
MAX_CARD_BYTES = 16 * 1024
MAX_TABS = 6
MAX_DATA_ITEMS = 50
TASK_KEY = re.compile(r"^[A-Z][A-Z0-9]{1,9}-[1-9][0-9]*$")


class CardError(FormError):
    """A card refused: the same 422 as FormError (the code, then up to MAX_PROBLEMS "path: message" lines)."""


def wrap(components: list, data: dict | None, prefix: str = "form") -> dict:
    # surfaceId = f"{prefix}-" + uuid.uuid4().hex[:12]; otherwise unchanged


def _library(message: dict) -> list[dict]:
    """a2ui-core's problems with the message against our catalog; empty when it passes."""
    processor = MessageProcessor([_catalog()], options=MessageProcessorOptions(validation_config=STRICT_VALIDATION))
    try:
        processor.process_messages([message])
    except A2uiError as error:
        return _problems(error)
    return []

# validate(message) becomes: if problems := _library(message): raise FormError("invalid_form", problems); then _check_limits


def _outside(components: list, allowed: frozenset[str]) -> list[dict]:
    """The components whose name is not one of `allowed`, as problems."""
    return [{"path": f"components.{c.get('id')}.component", "message": f"{c.get('component')!r} is not allowed here"}
            for c in components if not (isinstance(c.get("component"), str) and c["component"] in allowed)]


def _long_array(value: Any, path: str = "data") -> str | None:
    """The path of the first array in `value` with more than MAX_DATA_ITEMS items."""
    if isinstance(value, list):
        if len(value) > MAX_DATA_ITEMS:
            return path
        items = enumerate(value)
    elif isinstance(value, dict):
        items = value.items()
    else:
        return None
    for key, item in items:
        if found := _long_array(item, f"{path}.{key}"):
            return found
    return None


def clean_card(card: Any) -> dict:
    """The agent's {components, data?} as a validated, stored card surface. Raises CardError."""
    if not (isinstance(card, dict) and "components" in card and set(card) <= {"components", "data"}):
        raise CardError("invalid_card", [{"path": "card", "message": "must be {components, data?} and nothing else"}])
    if not (isinstance(card["components"], list) and all(isinstance(c, dict) for c in card["components"])):
        raise CardError("invalid_card", [{"path": "card", "message": "components must be a list of objects"}])
    if not isinstance(card.get("data", {}), dict):
        raise CardError("invalid_card", [{"path": "card", "message": "data must be an object"}])
    card = strip_nul_deep(card)
    components, data = card["components"], card.get("data")
    if _size(card) > MAX_CARD_BYTES:
        raise CardError("too_large", [{"path": "card", "message": f"over {MAX_CARD_BYTES} bytes"}])
    if len(components) > MAX_COMPONENTS:
        raise CardError("too_large", [{"path": "components", "message": f"over {MAX_COMPONENTS} components"}])
    if any(_is_input(c) for c in components):
        raise CardError("card_with_inputs")
    if problems := _outside(components, CARD_COMPONENTS):
        raise CardError("invalid_card", problems)
    for c in components:
        if c["component"] == "Tabs" and isinstance(c.get("tabs"), list) and len(c["tabs"]) > MAX_TABS:
            raise CardError("too_large", [{"path": f"components.{c.get('id')}.tabs", "message": f"over {MAX_TABS} tabs"}])
        task = c.get("task") if c["component"] == "TaskLink" else None
        if isinstance(task, str) and not TASK_KEY.fullmatch(task):
            raise CardError("invalid_card", [{"path": f"components.{c.get('id')}.task",
                                              "message": "not a task key such as MC-181"}])
    if path := _long_array(data):
        raise CardError("too_large", [{"path": path, "message": f"over {MAX_DATA_ITEMS} items"}])
    message = wrap(components, data, prefix="card")
    if problems := _library(message):
        raise CardError("invalid_card", problems)
    return message


def _catalog_for(allowed: frozenset[str]) -> dict:
    """The catalog cut down to `allowed` components (functions kept)."""
    doc = copy.deepcopy(_catalog_doc())
    doc["components"] = {k: v for k, v in doc["components"].items() if k in allowed}
    one_of = doc["$defs"]["anyComponent"]["oneOf"]
    doc["$defs"]["anyComponent"]["oneOf"] = [r for r in one_of if r["$ref"].rsplit("/", 1)[-1] in allowed]
    return doc


def form_guide() -> dict:   # replaces guide(): guide.md + _catalog_for(FORM_COMPONENTS) + example.json
def card_guide() -> dict:   # card_guide.md + _catalog_for(CARD_COMPONENTS) + card_example.json
```
`clean_form` gains, right after `form = strip_nul_deep(form)`: `if problems := _outside(form["components"], FORM_COMPONENTS): raise FormError("invalid_form", problems)`.

### C3. `card_example.json`
```json
{
  "components": [
    {"id": "root", "component": "Column", "children": ["tiles", "tabs"]},
    {"id": "tiles", "component": "Row", "children": ["passed", "failed", "time"]},
    {"id": "passed", "component": "StatTile", "label": "Passed", "value": "412", "tone": "good"},
    {"id": "failed", "component": "StatTile", "label": "Failed", "value": "3", "caption": "2 new since Monday", "tone": "bad"},
    {"id": "time", "component": "StatTile", "label": "Run time", "value": "4m 12s"},
    {"id": "tabs", "component": "Tabs", "tabs": [{"title": "Failing", "child": "failing"}, {"title": "Notes", "child": "notes"}]},
    {"id": "failing", "component": "List", "children": {"componentId": "row", "path": "/failing"}},
    {"id": "row", "component": "TaskLink", "task": {"@path": "key"}, "label": {"@path": "title"}},
    {"id": "notes", "component": "Text", "text": "Two of the failures are **flaky**."}
  ],
  "data": {"failing": [{"key": "MC-181", "title": "Login times out"}, {"key": "MC-182", "title": "Export is empty"}]}
}
```
(Use whatever relative-path syntax step 1 confirms a2ui-core accepts inside a template; `{"@path": "key"}` is the expected one.)

### C4. `card_guide.md`
```markdown
# Cards in show_card

A card shows a result in the thread of your task or chat, next to your reply: headline numbers, tabs, and lists
with links to tasks. It is read-only and a snapshot: it never updates. Cards use the A2UI v1.0 format with
MegooColab's catalog, which is in `catalog` next to this text.

## When

Only when a result reads better as tiles, tabs or a list of task links than as Markdown. Your Markdown reply
already has tables, links and Mermaid. Always reply in text as well.

## What you send

`show_card(key, title, text, card)`:
- `title` (1 to 120 characters) is the card's heading.
- `text` (1 to 500 characters) stands in for the card wherever it can't be drawn: notifications, search, and
  the prompts of other agents. Write it as a full, short summary of the card.
- `card` is `{"components": [...], "data": {...}}`. MegooColab adds the surface id, the catalog id and the envelope.

- `components` is a flat list. Each has a unique `id` and a `component` name; containers name children by id.
- The component with `"id": "root"` is the top. Every other component must be reachable from it.
- `data` (optional) is the data model that bound values read from (`{"@path": "/name"}`).

## Components

Layout:
- `Column`, `Row`: arrange their `children` top to bottom, or side by side.
- `Card`: a box around its single `child`.
- `Divider`: a line.
- `Text`: a short text with simple Markdown; Markdown links work.

Display:
- `Tabs`: up to 6 `tabs`, each `{title, child}`. The first is open.
- `List`: rows with a line between them. `children` is a list of ids, or a template
  `{"componentId": "<id>", "path": "/<array>"}` drawn once per item of that array, with paths inside the
  template relative to the item (`{"@path": "key"}`).
- `StatTile`: a `value` with its `label`, an optional `caption`, and a `tone`: `neutral`, `good`, `warning` or `bad`.
- `TaskLink`: a link to a task by its key (`task`, such as `MC-181`), followed by `label`. The label is your words,
  not the task's current title.

There are no inputs, buttons, images or media in a card.

## Limits

- At most 16 KB of card JSON and 60 components.
- At most 6 tabs in one `Tabs`, and 50 items in any array of `data`.
- At most 3 cards in one run, and 100 on one task.

Refusals: `invalid_card` followed by up to 10 `path: message` lines (it doesn't match the catalog, an empty title
or text, or a `TaskLink` whose literal `task` is not a task key), `card_with_inputs`, `too_large`, `too_many_cards`.
Nothing was stored: fix the card and call `show_card` again.

`example` next to this text is a complete card you can start from.
```

### C5. `TaskCard` model (in `backend/app/tasks/models.py`, after `Comment`)
```python
class TaskCard(IdMixin, Base):
    """MC-173: a read-only A2UI card an agent showed in the task's thread (app.tasks.cards.show). Its title and text
    stand in for it wherever it can't be drawn."""

    __tablename__ = "task_cards"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))  # a personal token's
    title: Mapped[str] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text)
    surface: Mapped[dict] = mapped_column(JSONB)  # the createSurface message (app.a2ui.service.clean_card)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
```
Migration constraint names: `task_cards_pkey`, `task_cards_task_id_fkey`, `task_cards_run_id_fkey`, `task_cards_agent_id_fkey`, `task_cards_user_id_fkey`; indexes `ix_task_cards_task_id`, `ix_task_cards_created_at`.

### C6. `backend/app/tasks/cards.py`
```python
"""Cards (MC-173): a read-only A2UI surface an agent shows in its task's or chat's thread, with a title and a short
text that stand in for it wherever it can't be drawn (notifications, search, other agents' prompts)."""

import uuid
from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import func, select

from app.a2ui import service as a2ui_service
from app.a2ui.service import CardError
from app.agent_runs.models import AgentRun
from app.auth.models import User
from app.core.events import Event, publish
from app.core.text import strip_nul
from app.tasks.models import Task, TaskCard

MAX_TITLE = 120
MAX_TEXT = 500
MAX_PER_RUN = 3
MAX_PER_TASK = 100


def _line(value: object, field: str, limit: int) -> str:
    value = strip_nul(value if isinstance(value, str) else "").strip()
    if not value:
        raise CardError("invalid_card", [{"path": field, "message": "must not be empty"}])
    if len(value) > limit:
        raise CardError("too_large", [{"path": field, "message": f"over {limit} characters"}])
    return value


async def _count(db, *where) -> int:
    return await db.scalar(select(func.count()).select_from(TaskCard).where(*where))


async def show(db, task: Task, run: AgentRun | None, user: User, title: object, text: object, card: object) -> TaskCard:
    """Store a card on the task. `run` is the calling run (locked, still running); None for a personal token, whose
    person is `user`. The task row is locked so two calls can't both pass the count limits. The caller commits."""
    title, text = _line(title, "title", MAX_TITLE), _line(text, "text", MAX_TEXT)
    surface = a2ui_service.clean_card(card)
    from app.workflow import engine  # local: the workflow imports the task modules

    if not await engine.lock_task_row(db, task.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task_not_found")
    if run is not None and await _count(db, TaskCard.run_id == run.id) >= MAX_PER_RUN:
        raise CardError("too_many_cards", [{"path": "card", "message": f"at most {MAX_PER_RUN} cards in one run"}])
    if await _count(db, TaskCard.task_id == task.id) >= MAX_PER_TASK:
        raise CardError("too_many_cards", [{"path": "card", "message": f"at most {MAX_PER_TASK} cards on one task"}])
    row = TaskCard(task_id=task.id, run_id=run.id if run else None, agent_id=run.agent_id if run else None,
                   user_id=None if run else user.id, title=title, text=text, surface=surface)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    await publish(db, Event(type="task.updated", project_id=task.project_id, task_id=task.id))
    if task.chat_id is not None:
        from app.chats.service import touch  # local: the chats modules import the engine

        await touch(db, task.chat_id)
    return row


async def of_runs(db, run_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[TaskCard]]:
    """Each run's cards, oldest first."""
    ids = list(run_ids)
    out: dict[uuid.UUID, list[TaskCard]] = {}
    if not ids:
        return out
    rows = await db.execute(select(TaskCard).where(TaskCard.run_id.in_(ids)).order_by(TaskCard.created_at, TaskCard.id))
    for row in rows.scalars():
        out.setdefault(row.run_id, []).append(row)
    return out
```

### C7. Activity item `card`
`ActivityItem.type: Literal["comment", "event", "question", "card"]`, new field `card: dict | None = None` with the comment `# type "card": {id, title, text, surface: the createSurface message, agent: {id, name}|None}`. `actor` = the `UserOut` of `TaskCard.user_id` (personal token), else None.

### C8. MCP tools (in `register_workflow_tools`)
```python
    @mcp.tool()
    async def show_card(key: str, title: str, text: str, card: dict[str, Any]) -> dict[str, Any]:
        """Show a read-only card in the task's or chat's thread, next to your reply, and keep working: `card` is
        {components, data?} (call get_card_guide first). `title` (at most 120 characters) is its heading; `text` (at
        most 500) stands in for it wherever it can't be drawn (notifications, search, other agents). Still reply in
        text. At most 3 cards in one run."""
        async with tool_session() as (db, user):
            task = await _task(db, user, key, "show_card", write=True)
            run = await live_run(db, task) if current_run.get() is not None else None
            row = await cards.show(db, task, run, user, title, text, card)
            return {"card_id": str(row.id)}

    @mcp.tool()
    async def get_card_guide() -> dict[str, Any]:
        """What a card for show_card may contain: instructions, MegooColab's A2UI catalog for cards and an example."""
        async with tool_session():
            return a2ui_service.card_guide()
```
`TOOL_ROLES`: lift the `ask_human` set into `ASKING = frozenset({...})` and use `"ask_human": ASKING, "show_card": ASKING` (comment: a reviewer judges what is there; a card is shown by those who may ask).

### C9. Frontend types (`frontend/src/lib/types.ts`)
```ts
/** An A2UI v1.0 `createSurface` message, as the backend stores it: a form question's or a card's. */
export type SurfaceMessage = {
  version: "1.0";
  createSurface: { surfaceId: string; catalogId: string; components: Record<string, unknown>[]; dataModel?: FormValues };
};
/** The `card` of an activity item with type "card" (the API types it as a loose object). */
export type ActivityCard = {
  id: string;
  title: string;
  text: string;
  surface: SurfaceMessage;
  /** the agent whose run showed it; null for a person's own agent (the item's actor) or a deleted agent */
  agent: { id: string; name: string } | null;
};
```

### C10. Frontend catalog components (`catalog.tsx`)
```tsx
/** A task key, as the backend's app.a2ui.service.TASK_KEY. */
export const TASK_KEY = /^[A-Z][A-Z0-9]{1,9}-[1-9][0-9]*$/;

/** Underline tabs with ui/Tabs' look and keys; the open tab is local state. Hidden panels stay mounted. */
export function Tabs({ id, tabs }: { id: string; tabs: { title: string; panel: ReactNode }[] }) {
  const [open, setOpen] = useState("0");
  const defs = tabs.map((t, i) => ({ id: `${id}-${i}`, label: t.title }));
  ... <UiTabs label="Tabs" tabs={defs} value={`${id}-${open}`} onChange={(v) => setOpen(v.slice(id.length + 1))} />
      {tabs.map((t, i) => <TabPanel key={i} id={`${id}-${i}`} active={String(i) === open}>{t.panel}</TabPanel>)}
}

/** Rows with a line between them; past about 15 rem it scrolls inside the card. */
export function List({ items }: { items: ReactNode[] }) {
  return (
    <div role="list" className="max-h-60 divide-y divide-line overflow-y-auto">
      {items.map((item, i) => <div key={i} role="listitem" className="py-1.5">{item}</div>)}
    </div>
  );
}

const TONE = { neutral: "", good: "text-green-ink", warning: "text-amber", bad: "text-pink" } as const;

/** The Dashboard Tile's look: a mono value, its label, a caption. */
export function StatTile({ label, value, caption, tone = "neutral" }: { label: string; value: string; caption?: string; tone?: keyof typeof TONE }) {
  return (
    <div role="group" aria-label={label} data-tone={tone} className="card min-w-0 px-3 py-2.5">
      <p className={`font-mono text-2xl leading-tight font-semibold ${TONE[tone] ?? ""}`}>{value}</p>
      <p className="text-xs text-muted-foreground">{label}</p>
      {caption && <p className="text-[11px] text-muted-foreground">{caption}</p>}
    </div>
  );
}

/** A task's key as a link to its board drawer, then the agent's label; anything else as plain text. */
export function TaskLink({ task, label }: { task: string; label?: string }) {
  if (!TASK_KEY.test(task)) return <span>{[task, label].filter(Boolean).join(" ")}</span>;
  return (
    <span>
      <Link href={`/projects/${task.replace(/-\d+$/, "")}/board?task=${task}`} className="font-mono text-cyan-ink underline">{task}</Link>
      {label && ` ${label}`}
    </span>
  );
}
```
(`UiTabs`/`TabPanel` imported from `@/components/ui/Tabs`; `Link` from `next/link`.)

### C11. `Surface.tsx` registration (inside `loadRenderer`)
```tsx
    implement(core.TabsApi, function TabsView({ props, buildChild, context }) {
      const { surfaceId } = useContext(FormContext);
      return <Tabs id={`${surfaceId}-${context.componentModel.id}`}
        tabs={(props.tabs ?? []).map((t) => ({ title: String(t.title ?? ""), panel: buildChild(t.child) }))} />;
    }),
    implement(core.ListApi, ({ props, buildChild }) => <List items={children(props.children, buildChild) ?? []} />),
    implement(StatTileApi, ({ props }) => <StatTile label={String(props.label ?? "")} value={String(props.value ?? "")}
      caption={props.caption == null ? undefined : String(props.caption)} tone={props.tone} />),
    implement(TaskLinkApi, ({ props }) => <TaskLink task={String(props.task ?? "")}
      label={props.label == null ? undefined : String(props.label)} />),
```
with, before the list:
```tsx
  const { z } = await import("zod");
  const S = core.CommonSchemas; // the export name step 1 confirmed
  const StatTileApi = { name: "StatTile", schema: z.object({ label: S.DynamicString, value: S.DynamicString,
    caption: S.DynamicString.optional(), tone: z.enum(["neutral", "good", "warning", "bad"]).optional(), weight: z.number().optional() }) };
  const TaskLinkApi = { name: "TaskLink", schema: z.object({ task: S.DynamicString, label: S.DynamicString.optional(), weight: z.number().optional() }) };
```
If step 1 found that `TabsApi`/`ListApi` are not exported, define them the same way (`tabs: z.array(z.object({ title: S.DynamicString, child: S.ComponentId }))`, `children: S.ChildList`, `direction`/`align` enums, `weight`).

## Steps

### 1. Catalog: add Tabs, List, StatTile and TaskLink, and confirm what the A2UI packages support
See step detail.

### 2. Validation: forms and cards each get their own component set, and clean_card checks a card
See step detail.

### 3. Data: the task_cards table and the TaskCard model
See step detail.

### 4. Service: cards.show stores a card and of_runs reads a turn's cards
See step detail.

### 5. Activity: a card is the thread's fourth item type
See step detail.

### 6. MCP: show_card and get_card_guide, and get_task without the surface
See step detail.

### 7. Text: prompts, the chat conversation and the reply notification read the card's title and text
See step detail.

### 8. Search: a task's card titles and texts are indexed with its comments
See step detail.

### 9. Methodology: the freestyle and finish texts teach show_card
See step detail.

### 10. Frontend: FormSurface becomes Surface, with a fallback, and the types follow the API
See step detail.

### 11. Frontend: the catalog's four display components, drawn by Surface
See step detail.

### 12. Frontend: ThreadCard and the card row in ActivityThread
See step detail.

### 13. Browser test: an agent shows a card in a chat
See step detail.

(Each step's full detail is the matching entry of the `steps` list; the contracts above are referenced as C1–C11.)

## Final verification
From `backend/`:
- `megoocolab-runner services run test -- uv run pytest -q -n auto`
- `megoocolab-runner services run migrate -- bash -c "uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head"`
- `uvx ruff check --select E9,F app tests`

From `frontend/`:
- `npm run gen:api` (no diff afterwards), `npx tsc --noEmit`, `npx eslint src/components/a2ui src/components/task src/components/workflow/QuestionCard.tsx src/lib/types.ts e2e/cards.spec.ts`, `npm test`
- `megoocolab-runner services run e2e -- npx playwright test e2e/cards.spec.ts e2e/forms.spec.ts --reporter=line`
