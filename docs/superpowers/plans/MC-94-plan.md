# MC-94 implementation plan: trigger prompts

## Goal
A project's managers set up triggers ("when this happens, send this prompt to an agent"). Each matching event starts a freestyle chat whose first message is the prompt, and whose agent is given a "What happened" block.

## Architecture
A new package, `backend/app/triggers/`:
- **Hook sites** call one function each in `emit.py`.
- **`emit.py`** checks the loop guard, matches the project's unpaused triggers through the event registry (`events.py`), and writes `pending` `TriggerFiring` rows inside a savepoint. It starts nothing.
- **`fire.py`** holds `trigger_loop`. It runs in the API process beside `cron_loop`. Every 5 s it claims the pending firings and does one of two things with each: it skips the firing with a reason, or it starts a freestyle chat through a function taken out of `chats/service.start_chat`.
- **`context.py`** adds the "What happened" block to a triggered chat's turns.
- **`workflow/freestyle.py`** ends a triggered chat after a reply when `keep_open` is false, and follows the trigger's notification switches.
- **REST API.** `service.py`, `schemas.py` and `router.py` follow `crons/`.

The frontend adds a Triggers tab, a list, an editor, a trigger page with its firings, and the trigger marks in Chats.

## Conventions for every step
- **Branch:** `megoo/MC-94-trigger-prompts`.
- **Commits:** one conventional commit per step, `type(area): sentence (MC-94)`. The body says why and what. It ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Backend tests** are run from `backend/`: `megoocolab-runner services run test -- uv run pytest <paths> -q`. Whole suite: `megoocolab-runner services run test -- uv run pytest -q -n auto`.
- **Frontend checks** are run from `frontend/`: `npx vitest run <path>`, `npx tsc --noEmit`, `npx eslint <changed files>`, `npm test`. Don't run Prettier.
- **Database code:** async SQLAlchemy throughout. Service functions never commit; routers and loops do.
- **Import cycles:** imports that would make a cycle are written locally inside the function, with a `# local:` comment, as the code does today.
- **Test world:** `tests/triggers/conftest.py` re-exports the Knowledge Base drafts world:
  ```python
  from tests.kb_drafts.conftest import world  # noqa: F401
  ```
  It is the same world `tests/crons/conftest.py` uses:
  - `w.me` is a member and owns the `laptop` agent, which is bound to PAY.
  - `w.manager` owns the `mgr_bot` agent, which is bound to PAY.
  - `w.project` is the PAY project's JSON.
  - `login(client, w.manager)` acts as the manager.

## File map

### Backend: new files
| File | Responsibility |
|---|---|
| `backend/app/triggers/__init__.py` | Empty package marker. |
| `backend/app/triggers/models.py` | `TriggerEvent`, `FiringStatus`, `Trigger`, `TriggerFiring` (Contract A). |
| `backend/app/triggers/events.py` | `EventSpec` registry: `validate`, `matches`, `describe`, `latest`; payload builders (Contract B). |
| `backend/app/triggers/emit.py` | One function per hook site; the loop guard; the savepoint (Contract C). |
| `backend/app/triggers/fire.py` | `tick`, `fire_one`, `trigger_loop`; skip reasons, hourly limit, problem notifications (Contract D). |
| `backend/app/triggers/context.py` | The "What happened" context provider, and `register()`. |
| `backend/app/triggers/schemas.py` | `TriggerIn`, `TriggerPatch`, `FiringSubject`, `FiringOut`, `TriggerOut` (Contract E). |
| `backend/app/triggers/service.py` | CRUD, `trigger_out`, `firing_out` (result and excerpt), `broken`, `firing_of_chat`, `chat_trigger`, `try_now`. |
| `backend/app/triggers/router.py` | REST under `/api/projects/{ref}/triggers`. |
| `backend/migrations/versions/<rev>_triggers.py` | The two tables (`down_revision = "c0b461aa6982"`). |
| `backend/tests/triggers/*` | The tests named in each step. |

### Backend: modified files
| File | Change |
|---|---|
| `backend/app/models.py` | `from app.triggers import models as triggers_models  # noqa: F401` |
| `backend/app/main.py` | Starts and stops `trigger_loop`; `register_triggers_context()`; includes `triggers_router`. |
| `backend/app/tasks/service.py` | `move_task` and `create_task` call emit. |
| `backend/app/workflow/engine.py` | `move_to_category` and `escalate` call emit. |
| `backend/app/chats/service.py` | `open_chat` is taken out of `start_chat`; `decide_board` calls emit; `chat_out` fills `trigger`. |
| `backend/app/chats/schemas.py` | `ChatTrigger`; `ChatOut.trigger`. |
| `backend/app/sprints/service.py` | `start` and `complete` call emit. |
| `backend/app/crons/turns.py` | `on_run_finished` calls emit. |
| `backend/app/git/events.py` | Merged PR events carry `base` and `title`. |
| `backend/app/git/activity.py` | `record` calls emit for an untracked merge (own webhook only). |
| `backend/app/workflow/finish.py` | `finish_workflow(..., *, tell=True)`. |
| `backend/app/workflow/freestyle.py` | End after a reply; notification switches. |

### Frontend (`frontend/src/`)
| File | Responsibility |
|---|---|
| `lib/triggers.ts` (new) | Types, query keys, hooks, and the texts for events, results, skips and broken references (Contract F). |
| `lib/api-types.ts` | Regenerated with `npm run gen:api`. |
| `app/(app)/projects/[key]/layout.tsx` and `__tests__/layout.test.tsx` | The "Triggers" tab after "Crons". |
| `app/(app)/projects/[key]/triggers/page.tsx` (new) | The list page. |
| `app/(app)/projects/[key]/triggers/[triggerId]/page.tsx` (new) | One trigger with its firings. |
| `components/triggers/TriggerList.tsx`, `TriggerEditor.tsx`, `FiringList.tsx` (new), `__tests__/triggers.test.tsx` (new) | The UI. |
| `components/chats/TriggerMessage.tsx` (new) | A triggered chat's first message: "Trigger X · runs as Y", the prompt, and the What happened block. |
| `components/chats/ChatList.tsx`, `ChatView.tsx`, `ChatsPage.tsx`, `ChatComposer.tsx`, `RoundSections.tsx` | The "Trigger" chip, the first message, the switch, and the ended note. |
| `components/chats/__tests__/fixtures.ts` | `trigger: null` default. |

---

## Contract A: models (`backend/app/triggers/models.py`)

```python
class TriggerEvent(StrEnum):
    task_finished = "task_finished"; task_created = "task_created"; task_moved = "task_moved"
    task_needs_person = "task_needs_person"; sprint_started = "sprint_started"
    sprint_completed = "sprint_completed"; epic_completed = "epic_completed"
    cron_found = "cron_found"; pr_merged = "pr_merged"

class FiringStatus(StrEnum):
    pending = "pending"; started = "started"; skipped = "skipped"

SKIP_REASONS = ("no_agent", "owner_gone", "rate_limited", "paused")
PROMPT_CHARS = 8_000   # a chat message's limit (chats.schemas.MAX_MESSAGE)
WHAT_CHARS = 6_000

class Trigger(IdMixin, Base):
    __tablename__ = "triggers"
    project_id = FK("projects.id", ondelete="CASCADE", name="triggers_project_id_fkey"), index=True
    name: String(100); event: String(30); config: JSONB, default=dict, server_default="{}"
    prompt: Text
    any_agent: Boolean, default True, server_default "true"
    agent_id: FK("agents.id", ondelete="SET NULL", name="triggers_agent_id_fkey"), nullable
    keep_open: Boolean default False server_default "false"
    notify_reply / notify_problems: Boolean default True server_default "true"
    paused: Boolean default False server_default "false"
    owner_id: FK("users.id", ondelete="SET NULL", name="triggers_owner_id_fkey")    # "runs as"
    created_by: FK("users.id", ondelete="SET NULL", name="triggers_created_by_fkey")
    created_at / updated_at: DateTime(timezone=True), server_default=func.now()

class TriggerFiring(IdMixin, Base):
    __tablename__ = "trigger_firings"
    __table_args__ = (Index("ix_trigger_firings_trigger_created", "trigger_id", "created_at"),
                      Index("ix_trigger_firings_status", "status"))
    trigger_id: FK("triggers.id", ondelete="CASCADE", name="trigger_firings_trigger_id_fkey")
    event: String(30)
    subject: JSONB            # {kind, label, title, link, note}
    what: Text                # at most WHAT_CHARS
    status: String(10), default FiringStatus.pending
    skip_reason: String(100) nullable
    agent_id: FK("agents.id", ondelete="SET NULL", name="trigger_firings_agent_id_fkey")
    chat_id: FK("chats.id", ondelete="SET NULL", name="trigger_firings_chat_id_fkey"),
             unique (UniqueConstraint("chat_id", name="trigger_firings_chat_id_key"))
    keep_open: Boolean default False
    tried: Boolean default False
    created_at: server_default now(); started_at: nullable
```
Use the same column style as `crons/models.py`: `Mapped[...]` and `mapped_column`.

## Contract B: event registry (`backend/app/triggers/events.py`)

```python
TASK_TYPES = ("story", "task", "bug")

@dataclass(frozen=True)
class Described:
    subject: dict   # {"kind", "label", "title", "link", "note"}
    what: str       # cut to models.WHAT_CHARS

@dataclass(frozen=True)
class EventSpec:
    id: TriggerEvent
    validate: Callable[[AsyncSession, Project, dict], Awaitable[dict]]  # cleaned config, or raises invalid(code)
    matches: Callable[[dict, dict], bool]                                # (config, payload), pure
    describe: Callable[[AsyncSession, dict], Awaitable[Described]]       # payload -> history row + What happened
    latest: Callable[[AsyncSession, Trigger], Awaitable[dict | None]] | None  # newest match, for Try it
    sprints_only: bool = False

REGISTRY: dict[str, EventSpec]
def spec(event: str) -> EventSpec           # unknown -> invalid("invalid_event")
def invalid(code: str) -> HTTPException     # 422 with detail=code
async def task_payload(db, task, *, from_column_id=None, actor=None, reason=None) -> dict
```

### Payloads
Plain dicts. Ids are strings.

| Kind | Payload |
|---|---|
| Task events | `{"task_id", "type", "label_ids": [..], "column_id" (the column it is now in), "from_column_id" or None, "actor": name, "reason"? (task_needs_person)}` |
| `epic_completed` | `{"epic_id", "task_id"}`, where `task_id` is the task whose finish completed the epic |
| Sprint events | `{"sprint_id"}` |
| `cron_found` | `{"cron_id", "cron_run_id"}` |
| `pr_merged` | `{"repo_id", "number", "title", "url", "branch", "base", "actor"}` |

The actor name, in order:
1. the agent's name while `app.mcp_server.auth.current_run.get()` is a run;
2. otherwise the user's name;
3. otherwise `"the workflow"`.

### `validate(db, project, config)`
Each event accepts only its own keys. An unknown key, or a value of the wrong type, gives `invalid_config`.

**Task events** (`task_finished`, `task_created`, `task_moved`, `task_needs_person`) need `task_types` and accept an optional `label_id`:
- `task_types` that is missing or empty gives `no_task_types`. A value outside `TASK_TYPES` gives `invalid_config`.
- `label_id` must be a `projects.models.Label` of the project. Otherwise: `invalid_label`.

**`task_moved`** also needs `column_id`, a `BoardColumn` of the project. Otherwise: `invalid_column`.

**`cron_found`** accepts an optional `cron_id`: a `Cron` of the project, or null for any cron. Otherwise: `invalid_cron`.

**Sprint events** in a project with `sprints_enabled` false give `invalid_event`.

**Every other event** takes `{}`.

The function returns the config with only these keys, UUIDs as strings, and `task_types` deduplicated in `TASK_TYPES` order.

### `matches(config, payload)`
| Event | Matches when |
|---|---|
| Task events | `payload["type"] in config["task_types"]`, and `config.get("label_id")` is None or in `payload["label_ids"]` |
| `task_moved` | the task rule, and also `payload["column_id"] == config["column_id"]` |
| `cron_found` | `config.get("cron_id") in (None, payload["cron_id"])` |
| All others | always |

A deleted column, label or cron never matches, because no payload carries it. So a trigger never widens to "any".

### `describe`
Links in the subject are app-relative. Links in `what` are absolute, built from `get_settings().public_url.rstrip("/")`.

| Event | Subject note | `what` |
|---|---|---|
| Task events | `kind="task"`, `label="PAY-12"`, `title`, `link=/projects/PAY/tasks/12`; note `finished`, `created`, `moved to <column name>`, or `needs a person: <reason with _ as spaces>` | `Task PAY-12 "<title>" (<type>; labels: a, b)`, then `Event: <moved from X to Y / created / finished / escalated: reason> by <actor>`, `Link: <abs>`, `Epic: PAY-3 "<title>"` when it has one, a blank line, `Description:` and the description |
| `epic_completed` | `kind="epic"`, the epic's key, title and link, note `completed` | The epic's line, its link, its description, then `Tasks:` with one line per child task: `- PAY-12 [<column name>] <title>` |
| Sprint events | `kind="sprint"`, `label=sprint.name`, `title=sprint.goal or ""`, `link=/projects/PAY/backlog`, note `started` or `completed` | Name, dates, goal; for completed, committed and completed points; then `Tasks:`, the sprint's tasks as `- KEY [column] title` |
| `cron_found` | `kind="cron_run"`, `label=cron.name`, `title=summary[:200]`, `link=crons.turns.cron_link(key, cron.id, run.id)`, note `<n> finding(s)` | `Cron "<name>" finished a run on <time> UTC with <n> findings.`, then `Summary:` and one entry per finding: `- <title>: <detail>` (plus ` (task KEY)` when it names one) |
| `pr_merged` | `kind="pr"`, `label="#<n>"`, `title`, `link=url`, note `merged into <base>` | `Pull request #<n> "<title>" was merged into <base> of repository <repo.name> by <actor>.`, then `Branch: <branch>` and `URL: <url>` |

Cutting text to `WHAT_CHARS`: cut the description or the list first, and add `(cut to fit)`.

### `latest(db, trigger)`
`latest` always returns a payload that `matches` accepts, or None.

| Event | Newest match |
|---|---|
| `task_finished` | The matching board task in a Done-category column, by `completed_at` desc |
| `task_created` | The matching board task, by `created_at` desc |
| `task_moved` | The matching board task in the configured column, by `updated_at` desc |
| `task_needs_person` | The matching board task whose `TaskWorkflow.needs == Needs.escalation`, by `updated_at` desc; `reason` is `wf.escalation_reason` |
| `sprint_started` | The active sprint, else the newest completed sprint |
| `sprint_completed` | The newest completed sprint, by `completed_at` |
| `epic_completed` | The newest epic that has at least one child and every child in Done |
| `cron_found` | The newest `CronRun` (of the configured cron, or of any of the project's crons) with `status == done` and a non-empty `report.findings` |
| `pr_merged` | `latest=None` |

A board task is `Task.in_chat.is_(False)` with `type` in `TASK_TYPES`.

## Contract C: emit (`backend/app/triggers/emit.py`)

```python
async def task_created(db, task: Task, actor: User | None) -> None
async def task_moved(db, task: Task, from_column_id: uuid.UUID | None, to_column: BoardColumn,
                     actor: User | None) -> None      # task_moved, task_finished, epic_completed
async def task_needs_person(db, task: Task, reason: str) -> None
async def sprint_started(db, sprint: Sprint) -> None
async def sprint_completed(db, sprint: Sprint) -> None
async def cron_found(db, cron: Cron, cron_run: CronRun) -> None
async def pr_merged(db, repo: ProjectRepository, ev: GitEvent) -> None
async def from_triggered_chat(db) -> bool             # the loop guard
async def _emit(db, project_id, events: list[tuple[str, Callable[[], Awaitable[dict]]]]) -> None
```

### `_emit`
```python
try:
    async with db.begin_nested():
        project = await db.get(Project, project_id)
        if project is None or project.status != ProjectStatus.active or await from_triggered_chat(db):
            return
        for event, build in events:
            triggers = (await db.execute(select(Trigger).where(
                Trigger.project_id == project_id, Trigger.event == event, Trigger.paused.is_(False)))).scalars().all()
            if not triggers:
                continue
            payload = await build()
            spec = events_mod.spec(event)
            hits = [t for t in triggers if spec.matches(t.config or {}, payload)]
            if hits:
                d = await spec.describe(db, payload)
                for t in hits:
                    db.add(TriggerFiring(trigger_id=t.id, event=event, subject=d.subject, what=d.what))
        await db.flush()
except Exception:
    log.exception("triggers: emit failed")
```

### Task events
They only fire for `not task.in_chat and task.type in TASK_TYPES`.

`task_moved` does all of this:
- emits `task_moved`;
- adds `task_finished` when `to_column.category == ColumnCategory.done` and the from-column's category was not done (no from-column counts as not done);
- in that same case, when `task.parent_id` is an epic and no child of the epic (`Task.parent_id == epic.id`, `in_chat` false) is in a non-Done column, also emits `epic_completed` with `{"epic_id", "task_id"}`.

### `from_triggered_chat`
1. Take `chat_id` from `app.tasks.service.event_origin.get()["id"]` when that is set.
2. Otherwise, when `app.mcp_server.auth.current_run.get()` is a run with `workflow_role == RunRole.freestyle` and a `task_id`, take that task's `chat_id`.
3. Return whether a `TriggerFiring` has that `chat_id`.

Without a chat, return False.

## Contract D: fire (`backend/app/triggers/fire.py`)
```python
FIRE_SECONDS = 5
HOURLY_LIMIT = 20
async def fire_one(db, firing: TriggerFiring) -> None
async def tick() -> None                       # one pass; commits, then engine.dispatch_queued
async def trigger_loop(stop: asyncio.Event) -> None   # as crons.scheduler.cron_loop
```

### `tick`
```python
async with SessionLocal() as db:
    rows = (await db.execute(select(TriggerFiring).where(TriggerFiring.status == FiringStatus.pending)
            .order_by(TriggerFiring.created_at).limit(50)
            .with_for_update(skip_locked=True))).scalars().all()
    for f in rows:
        await fire_one(db, f)
    await db.commit()
    await engine.dispatch_queued(db)
```

### `fire_one`
Steps in order:
1. Load the trigger and the project. If the project is no longer active, `db.delete(firing)` and return: nothing fires.
2. Skip `paused` when `trigger.paused and not firing.tried`. No notification.
3. Skip `owner_gone` in any of these cases:
   - the owner is None;
   - the owner's status is not `UserStatus.active`;
   - `projects.access.get_project_for(db, owner, project.key, write=True)` raises an `HTTPException`.
4. Skip `rate_limited` when the trigger already has `HOURLY_LIMIT` firings with `status == started` and `started_at > now - 1h`.
5. Pick the agent:
   - when `not trigger.any_agent`, the chosen agent, but only while `is_usable_binding(agent.id, project.id)` and `can_use_agent(owner, agent, project)` both hold; otherwise there is none;
   - otherwise `chats.service.pick_agent(db, owner, project)`, treating an `HTTPException` as none.

   No agent gives `no_agent`.
6. Start the chat:
   ```python
   chat, _ = await open_chat(db, owner, project, agent, trigger.prompt, ChatMode.freestyle,
                             title=f"{trigger.name} · {firing.subject['label']}"[:200])
   ```
   Then set `firing.status = started`, `started_at = now`, `chat_id`, `agent_id`, and `keep_open = trigger.keep_open`.

### Skipping
`_skip(db, trigger, project, firing, reason)` sets the status and the reason. When `trigger.notify_problems` is on and the reason is not `paused`, it calls `notifications.notify` with:
- recipients: `{trigger.owner_id} | crons.turns.project_managers(db, project.id)`;
- `Kind.needs_you`;
- title `Trigger <name> skipped`;
- body `SKIP_TEXT[reason]`;
- link `/projects/<KEY>/triggers/<id>`;
- `project_id`.

For `rate_limited` it notifies only when no other `rate_limited` firing of the trigger was created in the last hour.

```python
SKIP_TEXT = {
    "no_agent": "no agent can take it",
    "owner_gone": "the person it runs as can no longer start chats here",
    "rate_limited": "it already started 20 chats in the last hour",
    "paused": "the trigger was paused",
}
```

## Contract E: schemas (`backend/app/triggers/schemas.py`)
```python
class TriggerIn(BaseModel):
    name: NoNulStr = Field(min_length=1, max_length=100)
    event: NoNulStr = Field(max_length=30)            # checked by events.spec -> invalid_event
    config: dict = {}
    prompt: NoNulStr = Field(min_length=1, max_length=8_000)
    agent_id: uuid.UUID | None = None                 # None: any free agent
    keep_open: bool = False
    notify_reply: bool = True
    notify_problems: bool = True

class TriggerPatch(BaseModel):   # every field optional; agent_id given as null = any free agent
    name / event / config / prompt / agent_id / keep_open / notify_reply / notify_problems

class FiringSubject(BaseModel): kind: str; label: str; title: str; link: str | None; note: str
FiringResult = Literal["starting", "waiting_agent", "working", "question", "replied", "failed", "skipped"]
class FiringOut(BaseModel):
    id: uuid.UUID; created_at: datetime; subject: FiringSubject; agent: Named | None
    chat_id: uuid.UUID | None; result: FiringResult; excerpt: str | None
class TriggerOut(BaseModel):
    id; project_key; name; event: str; config: dict; prompt; any_agent: bool; agent: Named | None
    keep_open; notify_reply; notify_problems; paused; owner: Named | None; created_by: Named | None
    created_at; updated_at
    broken: Literal["column_deleted", "label_deleted", "cron_deleted"] | None
    last_firing: FiringOut | None
    try_subject: str | None     # "MC-100" (latest payload's described label), None when nothing / pr_merged
```
`chats/schemas.py` gets a class and a field:
```python
class ChatTrigger(BaseModel):
    id: uuid.UUID; name: str; what: str; keep_open: bool
```
`ChatOut.trigger: ChatTrigger | None = None`.

### `firing_out` result
| Condition | `result` | `excerpt` |
|---|---|---|
| `skipped` | `skipped` | the skip-reason code |
| `pending`, or no chat | `starting` | none |
| The chat round has an active run (`engine.active_run`) that is queued while `not registry.is_available(run.agent_id)` | `waiting_agent` | none |
| Any other active run | `working` | none |
| `wf.needs == Needs.question` | `question` | the open `WorkflowQuestion.body`, cut to 300 characters |
| The newest freestyle run is failed, or cancelled with `cancelled_by is None` | `failed` | `run.reason` |
| Otherwise | `replied` | the reply's first 300 characters (`freestyle._replies`, else `run.summary`) |

## Contract F: `frontend/src/lib/triggers.ts`
```ts
type S = components["schemas"];
export type Trigger = S["TriggerOut"]; export type Firing = S["FiringOut"];
export type TriggerEventId = "task_finished" | "task_created" | "task_moved" | "task_needs_person"
  | "sprint_started" | "sprint_completed" | "epic_completed" | "cron_found" | "pr_merged";
export type TaskTypeName = "story" | "task" | "bug";
export type TriggerConfig = { task_types?: TaskTypeName[]; label_id?: string | null; column_id?: string; cron_id?: string | null };
export const triggerKeys = { all: ["triggers"] as const, list: (p) => ["triggers", p] as const,
  one: (p, id) => ["triggers", p, id] as const, firings: (p, id) => ["triggers", p, id, "firings"] as const };
export const triggersPath = (project: string) => `/api/projects/${project}/triggers`;
export function useTriggers(project), useTrigger(project, id), useFirings(project, id)   // useQuery, as lib/crons.ts
export type EventInfo = { id: TriggerEventId; label: string; group: "Task events" | "Sprint events" | "Chains and larger events";
  fields: ("types" | "column" | "cron" | "webhook")[]; sprints?: true; canTry: boolean; example: string };
export const EVENTS: EventInfo[]   // the nine, in the design's order, "Shown as" labels; example = a sample What happened block
export const RESULT_TEXT: Record<Firing["result"], string> = { starting: "Starting", waiting_agent: "Waiting for the agent",
  working: "Working", question: "Asked a question", replied: "Replied", failed: "Couldn't finish", skipped: "Skipped" };
export const SKIP_TEXT: Record<string, string>      // same words as backend SKIP_TEXT, capitalised
export const BROKEN_TEXT = { column_deleted: "its column was deleted", label_deleted: "its label was deleted", cron_deleted: "its cron was deleted" };
export function eventInfo(id: string): EventInfo | undefined
export function filterText(t: Trigger, names: { columns: Map<string,string>; labels: Map<string,string>; crons: Map<string,string> }): string
  // e.g. "story, task, bug · label backend", "to Ready · bug", "Nightly deps", "any cron", "" for none
```

---

## Steps

### 1. Trigger and firing tables
- **New package:** add `backend/app/triggers/__init__.py` (empty) and `backend/app/triggers/models.py` exactly as Contract A.
- **Register the models:** in `backend/app/models.py`, add `from app.triggers import models as triggers_models  # noqa: F401` in alphabetical order, after `tasks` and `teams`.
- **Tests first:** add `backend/tests/triggers/__init__.py`, plus `backend/tests/triggers/conftest.py` re-exporting `world`. Then write `backend/tests/triggers/test_models.py`:
  - `test_a_trigger_keeps_its_settings_and_defaults`: insert a `Trigger` for PAY. The defaults are `any_agent True`, `keep_open False`, both notify flags True, `paused False`, `config {}`.
  - `test_deleting_a_trigger_deletes_its_firings`.
  - `test_a_chat_is_linked_to_one_firing_at_most`: a second firing with the same `chat_id` raises `IntegrityError`.
  - `test_deleting_the_project_deletes_its_triggers`.
- **Run:** `megoocolab-runner services run test -- uv run pytest tests/triggers/test_models.py -q`. Before the migration exists it fails, because the tables are missing.
- **Migration:**
  ```
  megoocolab-runner services run migrate -- bash scripts/makemigration.sh "triggers"
  ```
  Then rename the generated file to `<rev>_triggers.py`. Check:
  - the constraint names from Contract A;
  - `down_revision = "c0b461aa6982"`;
  - a `downgrade` that drops both tables.

  Check down and up:
  ```
  megoocolab-runner services run migrate -- bash -c "uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head"
  ```
- **Run again:** the tests pass.
- **Commit:** `feat(triggers): tables for triggers and their firings (MC-94)`.

### 2. Event registry: the four task events
Create `backend/app/triggers/events.py` with everything in Contract B that applies to `task_finished`, `task_created`, `task_moved` and `task_needs_person`, plus `task_payload`, `spec` and `invalid`.

**Tests first**, in `backend/tests/triggers/test_events_tasks.py`. Make tasks through the REST API as the manager (`POST /api/projects/PAY/tasks`; labels via `POST /api/projects/PAY/labels`):
- `test_validate_requires_task_types`: `{}` gives `no_task_types`; `{"task_types": ["epic"]}` gives `invalid_config`; `{"task_types": ["bug"], "extra": 1}` gives `invalid_config`.
- `test_validate_checks_label_and_column_belong_to_the_project`: another project's label gives `invalid_label`; a missing `column_id` on `task_moved` gives `invalid_column`; a good config comes back cleaned.
- `test_matches_filters_type_label_and_column`.
- `test_describe_task_has_key_link_and_untrusted_free_text`: the subject is `{kind: "task", label: "PAY-1", note: "finished"}`; the `what` holds the key, the title, the absolute link, the event line and the description; long descriptions are cut to `WHAT_CHARS`.
- `test_latest_finds_the_newest_matching_task`, for each of the four events. A subtask and a chat round are never returned.

**Run:**
```
megoocolab-runner services run test -- uv run pytest tests/triggers/test_events_tasks.py -q
```
The tests fail with an import error. Implement until they pass.

**Commit:** `feat(triggers): event registry for task events (MC-94)`.

### 3. Event registry: sprint, epic, cron and pull request events
Add to `REGISTRY` in `backend/app/triggers/events.py`: `sprint_started`, `sprint_completed` (`sprints_only=True`), `epic_completed`, `cron_found` and `pr_merged` (with `latest=None`), as in Contract B.

**Tests first**, in `backend/tests/triggers/test_events_other.py`:
- `test_sprint_events_are_refused_without_sprints`: set `sprints_enabled` false on the project; `validate` raises `invalid_event`.
- `test_cron_found_accepts_any_or_one_of_the_projects_crons`: another project's cron gives `invalid_cron`; `matches` handles both `None` and a specific `cron_id`.
- `test_describe_sprint_lists_its_tasks`.
- `test_describe_epic_lists_its_tasks`.
- `test_describe_cron_lists_findings`: create a `Cron` and a `CronRun` with `report={"summary": "...", "findings": [{"title", "detail"}], "submitted": True}` and status `done`.
- `test_describe_pr`: the note is `merged into main`.
- `test_latest_for_sprint_epic_and_cron`: each returns the newest match or None; `REGISTRY["pr_merged"].latest is None`.
- `test_other_events_take_no_config`: `{"x": 1}` gives `invalid_config`.

**Run:**
```
megoocolab-runner services run test -- uv run pytest tests/triggers/test_events_other.py -q
```
It fails (KeyError). Implement until it passes.

**Commit:** `feat(triggers): sprint, epic, cron and pull request events (MC-94)`.

### 4. Emit, the loop guard, and the task hooks
Create `backend/app/triggers/emit.py` as in Contract C, with `_emit`, `from_triggered_chat`, `task_created` and `task_moved`.

**Hook sites.** Import `from app.triggers import emit as trigger_emit`, locally where a cycle would appear.
- **`tasks/service.py::create_task`:** after `record_event(... "created" ...)`, add `if not task.in_chat: await trigger_emit.task_created(db, task, user)`.
- **`tasks/service.py::move_task`:** save `old_column_id = task.column_id` before `apply_column`. After `apply_column`, add `if column.id != old_column_id: await trigger_emit.task_moved(db, task, old_column_id, column, user)`.
- **`workflow/engine.py::move_to_category`:** after the `status_changed` event, add `await trigger_emit.task_moved(db, task, frm, column, None)`.
- **`chats/service.py::decide_board`:** after `task_changed(db, task, "task.created")`, add `await trigger_emit.task_created(db, task, user)`.

**Tests first**, in `backend/tests/triggers/test_emit_tasks.py`. Add `backend/tests/triggers/helpers.py` with `async def make_trigger(db, w, event, config=None, **kw) -> Trigger`, which inserts a trigger owned by `w.manager` and commits.
- `test_creating_a_task_writes_a_pending_firing`: types and label match, and the row's subject and `what` are filled; a non-matching type writes nothing; a subtask writes nothing.
- `test_moving_to_done_fires_moved_and_finished`; moving between two non-Done columns fires `task_moved` only.
- `test_the_workflow_finishing_a_task_fires_finished`: call `engine.move_to_category(db, task, ColumnCategory.done)`.
- `test_epic_completed_fires_only_with_the_last_task`, and fires again after a reopen and a re-finish.
- `test_paused_trigger_and_closed_project_write_nothing`.
- `test_chat_rounds_never_fire_but_adding_one_to_the_board_does`, using `tests/chats/helpers` `start` and `decide_board`.
- `test_loop_guard`:
  - while `current_run` is set to the freestyle run of a chat that has a firing, `create_task` and `move_task` write nothing;
  - the same with a person's chat (no firing) writes firings;
  - the same holds through `event_origin.set({"id": str(chat.id), "title": "x"})`.
- `test_a_failing_emit_never_fails_the_action`: monkeypatch `events.REGISTRY["task_created"]` to one whose `describe` raises; `POST /api/projects/PAY/tasks` still returns 201 and the task exists.

**Run:**
```
megoocolab-runner services run test -- uv run pytest tests/triggers/test_emit_tasks.py tests/tasks tests/chats -q -n auto
```
Implement until it is green.

**Commit:** `feat(triggers): task events fire from the board, the workflow and chats (MC-94)`.

### 5. Escalation, sprint and cron hooks
In `backend/app/triggers/emit.py`, add `task_needs_person`, `sprint_started`, `sprint_completed` and `cron_found` (Contract C).

**Hooks:**
- **`workflow/engine.py::escalate`:** after `record_workflow_event(... "workflow.escalated" ...)`, add `await trigger_emit.task_needs_person(db, task, reason)`. Only escalations count, never approvals or questions.
- **`sprints/service.py::start`:** at the end, `await trigger_emit.sprint_started(db, sprint)`.
- **`sprints/service.py::complete`:** at the end, `await trigger_emit.sprint_completed(db, sprint)`.
- **`crons/turns.py::on_run_finished`:** before `tell_outcome`, add:
  ```python
  if cron is not None and cron_run.status == CronRunStatus.done and (cron_run.report or {}).get("findings"):
      await trigger_emit.cron_found(db, cron, cron_run)
  ```

**Tests first**, in `backend/tests/triggers/test_emit_other.py`:
- `test_an_escalation_fires_needs_person`: `await engine.escalate(db, wf, "retries_exhausted")` on a board task's workflow writes a firing with the note `needs a person: retries exhausted`; `wait_for(... Needs.question)` writes none.
- `test_starting_and_completing_a_sprint_fire`, through REST `POST /api/sprints/{id}/start` and `/complete`, as the existing sprint tests call them. Look in `backend/tests/sprints` for the paths.
- `test_sprints_started_by_a_triggered_chat_fire_nothing`: `current_run` is set as in step 4.
- `test_a_cron_run_with_findings_fires_and_one_without_does_not`: build an `AgentRun` and a `CronRun` as `backend/tests/crons/test_scheduler.py` does, then call `turns.on_run_finished`.
- `test_cron_found_for_one_cron_ignores_others`.

**Run:**
```
megoocolab-runner services run test -- uv run pytest tests/triggers/test_emit_other.py tests/sprints tests/crons tests/workflow -q -n auto
```

**Commit:** `feat(triggers): escalations, sprints and cron findings fire triggers (MC-94)`.

### 6. Merged pull requests outside a task
- **`git/events.py`:** in `_github_like` (`action == "closed"`) and in `_gitlab` (`action in ("merge", "close")`), the event data becomes:
  ```python
  {"url": url, "title": excerpt(...title...), "base": _str(base ref / target_branch)}
  ```
  It uses the same expressions as the `pr_opened` branch.
- **`git/activity.py::record`:** inside the `if task is None or (...)` block, before `continue`, add:
  ```python
  if task is None and repo is not None and ev.kind == "git.pr_merged":
      await trigger_emit.pr_merged(db, repo, ev)
  ```
  Use the import alias `trigger_emit`: `record` already has a local named `trigger`.
- **`emit.pr_merged`:** returns unless `ev.data.get("base") == repo.default_branch`. Its payload holds `repo_id`, `number`, `title`, `url`, `branch`, `base`, and `actor` (`ev.actor["name"]`). The project is `repo.project_id`.

**Tests first:**
- In `backend/tests/triggers/test_emit_git.py`, build `GitConnection`, `ProjectRepository` and payload fixtures as `backend/tests/git` does. Find them with `grep -rn "parse_delivery\|activity.record" backend/tests/git`.
  - `test_untracked_merge_into_default_branch_fires`, for GitHub, Gitea and GitLab payloads.
  - `test_merge_into_another_branch_or_of_a_tracked_pr_fires_nothing`: a `megoo/PAY-1` head branch, and a `GitPrLink`.
  - `test_shared_connection_address_fires_nothing` (`repo=None`).
- Update every assertion in `backend/tests/git` that expects a merged event's data to equal `{"url": ...}`. Find them with `grep -rn 'pr_merged' backend/tests/git`.

**Run:**
```
megoocolab-runner services run test -- uv run pytest tests/triggers/test_emit_git.py tests/git -q -n auto
```

**Commit:** `feat(triggers): a pull request merged outside a task fires triggers (MC-94)`.

### 7. A shared way to open a chat, and ChatOut.trigger
**`chats/service.py`.** Take the start of `start_chat` out into a new function:
```python
async def open_chat(db, user: User, project: Project, agent: Agent, message: str, mode: ChatMode,
                    *, title: str | None = None) -> tuple[Chat, Task]:
    chat = Chat(project_id=project.id, started_by=user.id, agent_id=agent.id,
                title=(title or first_line(message))[:200], mode=mode)
    db.add(chat); await db.flush()
    task = await create_round(db, user, chat, message)
    return chat, task
```
`start_chat` then calls `get_project_for(..., write=True)`, `_chosen_agent`, `open_chat` and `link_images`. It behaves as before.

**Schemas and `chat_out`:**
- Add `ChatTrigger` and `ChatOut.trigger` from Contract E to `chats/schemas.py`.
- Create `backend/app/triggers/service.py` with two functions:
  - `firing_of_chat(db, chat_id) -> TriggerFiring | None`;
  - `chat_trigger(db, chat_id) -> ChatTrigger | None`, which joins `Trigger` to give `{id, name, what: firing.what, keep_open: firing.keep_open}`.
- `chat_out` sets `trigger=await chat_trigger(db, chat.id)`, imported locally.

**Tests first**, in `backend/tests/triggers/test_chat_trigger.py`:
- `test_an_ordinary_chat_has_no_trigger`: `GET /api/chats/{id}` has `trigger` null.
- `test_open_chat_uses_the_given_title_and_message`: the round's `description_md` is the message, and the chat title is the given one.
- `test_a_chat_linked_to_a_firing_shows_its_trigger`; once the trigger is deleted, `trigger` is null and the chat stays.

**Run:**
```
megoocolab-runner services run test -- uv run pytest tests/triggers/test_chat_trigger.py tests/chats -q -n auto
```

**Commit:** `refactor(chats): open a chat from one place, and show the trigger that started it (MC-94)`.

### 8. The trigger loop starts chats
- Create `backend/app/triggers/fire.py` as in Contract D.
- **`main.py`:**
  - add `from app.triggers.fire import trigger_loop`;
  - start it with `trigger_task = asyncio.create_task(trigger_loop(stop_routing))` beside `cron_task`;
  - in `finally`, add `with contextlib.suppress(Exception): await asyncio.wait_for(trigger_task, 5)`.

**Tests first**, in `backend/tests/triggers/test_fire.py`. Write pending firings directly, with `make_trigger` and `TriggerFiring(status="pending", subject={...,"label": "PAY-1"}, what="...")`, then `await fire.tick()`:
- `test_a_firing_starts_a_freestyle_chat`:
  - the chat is titled `<name> · PAY-1`, is `freestyle`, and has `started_by == manager`;
  - its round's `description_md` is the prompt;
  - one queued `freestyle` run;
  - the firing is `started` with `chat_id`, `agent_id` and `keep_open` copied.
- `test_the_chosen_agent_or_any_usable_one`: the chosen `mgr_bot`; with `any_agent`, `pick_agent` is used; when the chosen agent is unbound, the result is `no_agent`.
- `test_skip_reasons`:
  - `paused` (but a `tried` firing on a paused trigger still starts);
  - `owner_gone`: the owner deactivated, or `owner_id` None;
  - `no_agent`.
- `test_hourly_limit`: 20 started firings in the last hour make the 21st `rate_limited`; only one notification goes out for two rate-limited firings in the hour.
- `test_problem_notifications_follow_the_switch`: the manager gets a `needs_you` notification linking `/projects/PAY/triggers/<id>`; none with `notify_problems` false; none for `paused`.
- `test_a_closed_project_drops_pending_firings`.
- `test_firings_already_locked_are_skipped`: two ticks in parallel start one chat per firing.

**Run:**
```
megoocolab-runner services run test -- uv run pytest tests/triggers/test_fire.py -q
```

**Commit:** `feat(triggers): pending firings start freestyle chats (MC-94)`.

### 9. What happened, given to the agent
Create `backend/app/triggers/context.py`:
```python
WHAT_HAPPENED = ("## What happened\n\nA trigger of this project (\"{name}\") started this chat when the event below "
                 "happened. Nobody may be watching this chat: do what the first message asks, and say in your reply "
                 "what you did.\n\n{block}")
async def what_happened(db, task, role) -> str | None:
    if role != RunRole.freestyle or task.chat_id is None: return None
    found = await chat_trigger(db, task.chat_id)
    return None if found is None else WHAT_HAPPENED.format(name=_escape(found.name), block=wrap_untrusted("trigger_event", found.what))
def register() -> None: append to workflow.context.context_providers once (as chats/context.register)
```
In `main.py`, import `register as register_triggers_context` and call it after `register_chats_context()`. No methodology text changes.

**Tests first**, in `backend/tests/triggers/test_context.py`:
- `test_a_triggered_chats_turn_gets_the_block_wrapped_as_untrusted`: call `what_happened` with `RunRole.freestyle`. It includes `<untrusted source="trigger_event">`, and a `<script>` in the what text comes out escaped.
- `test_no_block_for_ordinary_chats_or_other_roles`.
- `test_register_is_idempotent`.

**Run:**
```
megoocolab-runner services run test -- uv run pytest tests/triggers/test_context.py -q
```

**Commit:** `feat(triggers): the agent is told what happened (MC-94)`.

### 10. A triggered chat ends after the reply
- **`workflow/finish.py`:** `finish_workflow(db, wf, task, actor_id, *, tell: bool = True)`. The "Chat finished" notification is sent only when `tell` is true.
- **`workflow/freestyle.py`:** add `_end_if_triggered`:
  ```python
  async def _end_if_triggered(db, wf, task) -> bool:
      firing = await firing_of_chat(db, task.chat_id) if task.chat_id else None   # local import
      if firing is None or firing.keep_open: return False
      chat = (await db.execute(select(Chat).where(Chat.id == task.chat_id)
              .with_for_update(skip_locked=True))).scalar_one_or_none()
      if chat is None or chat.status == ChatStatus.ended: return False   # a person is acting on it: stays open
      wf.stage = Stage.done
      await finish.finish_workflow(db, wf, task, None, tell=False)
      chat.status = ChatStatus.ended; chat.ended_at = chat.last_activity_at = datetime.now(UTC)
      return True
  ```
  `skip_locked` keeps the lock order chat → task → workflow safe.
- **`handle_turn_end`:** call it after `wait_for(... Needs.reply ...)` and before `_notify_replied`. Do not call it on the question path, the deliver path or the queued-turn path. `wait_after_failure` never calls it.
- **`_notify_replied`** gets the trigger's switches. On the firing's own turn (no earlier freestyle `AgentRun` of the task):
  - a reply is sent only when `trigger.notify_reply` is on;
  - a failure is sent only when `trigger.notify_problems` is on.

  Later turns notify as before.

**Tests first**, in `backend/tests/triggers/test_turn_end.py`. Fire a trigger via `fire.tick()`, then end its run with `tests.workflow.test_freestyle_engine._end`:
- `test_the_chat_ends_after_the_reply_by_default`: the chat is `ended`, the workflow `finished`, and there is no `Chat finished` notification.
- `test_keep_open_keeps_the_chat_waiting_for_a_reply`: the state is `reply`.
- `test_a_question_keeps_it_open`: open a `WorkflowQuestion` for the run, then end it; the state is `question`.
- `test_a_failed_turn_keeps_it_open`.
- `test_notifications_follow_the_switches`.
- `test_ordinary_freestyle_chats_are_unchanged`.

**Run:**
```
megoocolab-runner services run test -- uv run pytest tests/triggers/test_turn_end.py tests/chats tests/workflow -q -n auto
```

**Commit:** `feat(triggers): a triggered chat ends when the agent replies, unless kept open (MC-94)`.

### 11. Triggers API: create, read, edit, pause, delete
Create `backend/app/triggers/schemas.py` (Contract E). `service.py` gets these functions:

| Function | Does |
|---|---|
| `get_trigger(db, project, id, *, lock=False)` | 404 `trigger_not_found` when missing |
| `create(db, user, project, data)` | Checks the event with `events.spec`; refuses a sprint event without sprints (`invalid_event`); cleans the config with `validate`; checks the agent with `_check_agent`, copied from `crons/service.py`; sets `owner_id = created_by = user.id` and `any_agent = agent_id is None`; writes audit `trigger.created` |
| `update(db, user, project, trigger, data)` | Validates the merged event and config; checks the resulting agent against the editor even when unchanged (when not `any_agent`); sets `owner_id = user.id` and `updated_at = func.now()`; writes audit `trigger.updated` |
| `set_paused(db, user, trigger, paused)` | Audit `trigger.paused` or `trigger.resumed`. It does not change the owner |
| `delete(db, user, trigger)` | Audit `trigger.deleted`. The chats stay |
| `broken(db, trigger)` | Checks `column_id`, `label_id` and `cron_id` against the project |
| `firing_out(db, firing)` | Contract E's result table |
| `trigger_out(db, trigger)` | `last_firing` is the newest firing; `try_subject` is `describe(latest)`'s `subject["label"]`, or None when `latest` is None or returns None |

`router.py` follows `crons/router.py`:
- `GET` and `POST /api/projects/{ref}/triggers`;
- `GET`, `PATCH` and `DELETE /{trigger_id}`;
- `POST /{trigger_id}/pause` and `/resume`.

Members read through `get_project_for`. Writes go through `_managed` (`write=True` plus `require_manage`). Pause, resume and delete work on a closed project (`_managed_any_status`). Include `triggers_router` in `main.py`.

**Tests first**, in `backend/tests/triggers/test_api.py`:
- `test_members_read_managers_and_admins_write`: a member gets 403 on POST and PATCH.
- `test_validation_codes`: `invalid_event`, `invalid_config`, `invalid_column`, `invalid_label`, `invalid_cron`, `no_task_types`, `agent_not_available` (the member's `laptop` chosen by the manager).
- `test_runs_as_moves_to_the_last_editor_not_on_pause`: an admin PATCH makes the admin the owner; pause and resume keep it.
- `test_broken_reference`: delete the configured column; `broken == "column_deleted"`, and a matching move writes no firing.
- `test_last_firing_and_results`: skipped, starting, working and replied.
- `test_delete_cascades_firings_and_keeps_chats`.
- `test_pause_resume_delete_on_a_finished_project`.
- `test_audit_records`.

**Run:**
```
megoocolab-runner services run test -- uv run pytest tests/triggers/test_api.py -q
```

**Commit:** `feat(triggers): API to manage a project's triggers (MC-94)`.

### 12. Try it, and the firing history
- **`service.try_now(db, user, project, trigger) -> TriggerFiring`:**
  1. `spec.latest` must exist and return a payload. Otherwise 422 `nothing_to_try`. That covers `pr_merged` and a trigger with nothing to match yet.
  2. `describe` the payload, and insert `TriggerFiring(tried=True, status=pending, ...)`.
  3. Call `await fire.fire_one(db, firing)`. It counts toward the hourly limit and works on a paused trigger.
  4. Write audit `trigger.tried`.
- **Router:**
  - `POST /{trigger_id}/try` (201, managers, `write=True`): commit, then `engine.dispatch_queued(db)`, and return `FiringOut`.
  - `GET /{trigger_id}/firings?limit=` (`Query(50, ge=1, le=200)`): newest first.

**Tests first**, in `backend/tests/triggers/test_try.py`:
- `test_try_fires_on_the_newest_match_now`: a chat starts and the firing is `tried`.
- `test_try_on_a_paused_trigger_works`.
- `test_try_counts_toward_the_hourly_limit`.
- `test_nothing_to_try_and_pr_merged_are_refused`.
- `test_firings_newest_first_with_limit`.
- `test_members_cannot_try`.

**Run:**
```
megoocolab-runner services run test -- uv run pytest tests/triggers -q -n auto
```
Then run the whole backend suite.

**Commit:** `feat(triggers): try a trigger now, and list its firings (MC-94)`.

### 13. Frontend: types, the tab and the list
1. In `frontend/`, run `npm run gen:api`. Confirm that `TriggerOut`, `FiringOut` and `ChatOut.trigger` are in `src/lib/api-types.ts`.
2. Create `src/lib/triggers.ts` (Contract F).
3. **Layout:** in `src/app/(app)/projects/[key]/layout.tsx`, add `{ href: \`/projects/${p.key}/triggers\`, label: "Triggers" }` after Crons. Update `__tests__/layout.test.tsx` to expect `["Board","Chats","Crons","Triggers","Settings","Questions"]`.
4. **List page:** `src/app/(app)/projects/[key]/triggers/page.tsx` is like `crons/page.tsx`. It uses `usePageTitle("Triggers", ...)` and renders `<TriggerList projectKey canManage={projectRights(me, project).canManage} />`.
5. **`components/triggers/TriggerList.tsx`:**
   - a `<ul>` with one row per trigger:
     - a link to `/projects/KEY/triggers/<id>` with the name and the prompt's first line;
     - the event text, `eventInfo().label` plus `filterText`, using `useColumns`, `useLabels` and `useCrons`;
     - `broken` shown as `BROKEN_TEXT` in pink;
     - the last firing: its subject label, `RESULT_TEXT`, and `SKIP_TEXT` for skips;
     - `Paused` when paused.
   - `New trigger` and `Pause`/`Resume` show only with `canManage`. They POST, then invalidate `triggerKeys.all`.
   - Errors show in `role="alert"`.
   - An empty list says `No triggers yet.`
   - `New trigger` opens `TriggerEditor`. Until step 14 lands, make it a small stub that renders `<Dialog open onClose title="New trigger · KEY" />`.

**Tests first**, in `src/components/triggers/__tests__/triggers.test.tsx`. Use the `crons.test.tsx` pattern: `vi.stubGlobal("fetch")`, a fresh `QueryClient`, and `vi.mock("next/navigation")`.
- `TriggerList shows rows, results and skip texts`.
- `TriggerList pauses and resumes` (a POST to `/pause`).
- `members see no controls`.
- `a broken trigger says why`.

**Run:**
```
npx vitest run src/components/triggers "src/app/(app)/projects/[key]/__tests__/layout.test.tsx"
```
Then `npx tsc --noEmit` and eslint on the changed files.

**Commit:** `feat(triggers): Triggers tab and list (MC-94)`.

### 14. Frontend: the trigger editor
`src/components/triggers/TriggerEditor.tsx` has props `{ projectKey: string; trigger?: Trigger; onClose: () => void }` and uses the primitives `CronEditor` uses (`Dialog wide`, `Input`, `Select`, native checkboxes and radios, a textarea).

**Fields, top to bottom:**
1. **Name.**
2. **When:** a `Select` of `EVENTS`, grouped with `<optgroup>`. The sprint events are hidden when `project.sprints_enabled` is false.
3. **Fields for the chosen event:**
   - `types`: "Only for" checkboxes for Story, Task and Bug (all ticked by default) and a Label select (Any label, or the project's labels);
   - `column`: a "Column" select of `useColumns`;
   - `cron`: a "Cron" select (Any cron, or `useCrons`);
   - `webhook`: a note. It reads "Needs the repository's own webhook" plus the status from `useRepos` (`webhook_status === "working"` means set up). With no repository set up it says the trigger will not fire until the webhook is set up.
4. **Prompt:** a textarea (`maxLength` 8000), labelled `Prompt`.
5. **Example:** `What happened (added under your prompt)`, with `eventInfo(event).example` in a `<pre>`.
6. **Agent:** a `Select` as in `CronEditor`, `Any free agent of KEY` plus usable agents.
7. **After the agent replies:** radios `End the chat` (default) and `Keep the chat open`, plus a note that a question or a failure keeps it open.
8. **Tell me:** checkboxes `When the agent replies` and `When a firing is skipped or fails`.

**Saving:** POST, or PATCH for an edit, with:
```js
{ name, event, config, prompt, keep_open, notify_reply, notify_problems }
```
`config` holds only the keys the event uses. `agent_id` is sent only when it changed (the same rule as `CronEditor`). Then invalidate and close. Saving is disabled while the name or prompt is empty, when no type is ticked, or when the column is unset for `task_moved`. When editing it notes: "Saving makes you the person it runs as." Wire it into `TriggerList`, replacing the stub.

**Tests first** (append to `triggers.test.tsx`):
- `TriggerEditor shows the right fields for each event`: change When through the nine events and assert on the fields shown.
- `posts the body for task_moved`: `config {task_types, column_id}` and `agent_id: null`.
- `posts cron_found with any cron`: `config {cron_id: null}`.
- `pr_merged shows the webhook note`.
- `edit sends a PATCH without agent_id when unchanged`.
- `can't save with no type ticked`.

**Run:**
```
npx vitest run src/components/triggers
```
Then tsc and eslint.

**Commit:** `feat(triggers): editor for a trigger's event, prompt and agent (MC-94)`.

### 15. Frontend: one trigger and its firings
- **`src/app/(app)/projects/[key]/triggers/[triggerId]/page.tsx`**, like `crons/[cronId]/page.tsx`:
  - `NotFoundView` on a 404;
  - a header with a back link, the name, the event text, `Runs as <owner>`, the agent, and `Paused`/`broken` when they apply;
  - the prompt in a `<pre>`.
  - **Manager buttons:**
    - `Edit` opens `TriggerEditor`;
    - `Pause`/`Resume`;
    - `Try it on <try_subject>` shows only when `try_subject` is set and `eventInfo().canTry`. It POSTs `/try`, then invalidates `triggerKeys.all`;
    - `Delete`, with `useConfirm` (`Delete <name>?`, "Its firings go with it. The chats it started stay.", ok `Delete trigger`), then `router.push` to the list.
  - Then `<FiringList projectKey triggerId />`.
- **`src/components/triggers/FiringList.tsx`:** a table with the header `Fired at | What happened | Agent | Result`. Each row shows:
  - the local time;
  - the subject label and title, linked to `subject.link`, with `subject.note`;
  - the agent name, or `—`;
  - `RESULT_TEXT[result]`, linked to `/chats/<chat_id>` when there is one, with the excerpt below (`SKIP_TEXT` for skipped).

  With no firings it says `No firings yet.`

**Tests first** (append to `triggers.test.tsx`):
- `the trigger page shows firings and links to their chats`.
- `Try it posts and is hidden for pr_merged or with no try_subject`.
- `delete asks first`.
- `members see no buttons`.

**Run:**
```
npx vitest run src/components/triggers
```
Then tsc and eslint.

**Commit:** `feat(triggers): trigger page with its firing history (MC-94)`.

### 16. Frontend: triggered chats in Chats
- **`components/chats/__tests__/fixtures.ts`:** `chat()` defaults to `trigger: null`.
- **The chip:** a `TriggerChip` exported from `components/chats/TriggerMessage.tsx` renders `<span ...>Trigger</span>` in amber, styled like `FreestyleChip`. `ChatList` shows it before the title when `c.trigger`. The `ChatView` header shows it beside `FreestyleChip`.
- **`TriggerMessage({ chat, prompt })`:** a section `aria-label="First message"` with:
  - the heading `Trigger <chat.trigger.name> · runs as <chat.started_by?.name>`;
  - the prompt in a `<pre>`;
  - a `What happened` sub-heading with `chat.trigger.what` in a `<pre>`.

  `RoundSections` renders it first for round 1 when `chat.trigger`, with `prompt = task.data?.description_md ?? ""`.
- **`ChatsPage`:**
  ```ts
  const [triggered, setTriggered] = useStoredState<boolean>("chats.triggered", true, "local");
  ```
  A checkbox labelled `Chats started by triggers` sits beside `StateFilter`. When it is off, chats with `trigger` are left out before counting and filtering.
- **`ChatComposer`:** when the chat is ended and `chat.trigger && !chat.trigger.keep_open`, it says `This chat ended when the agent replied.` instead of `This chat has ended.`

**Tests first:**
- In `src/components/chats/__tests__/ChatTrigger.test.tsx`:
  - the chip in the list and in the header;
  - the first message with its heading, its prompt and its What happened block;
  - the ended note.
- In `ChatsPage.test.tsx`: `hides triggered chats when the switch is off, and remembers it`.

**Run:**
```
npx vitest run src/components/chats
```
Then `npx tsc --noEmit`, eslint on the changed files, and the full `npm test`.

**Commit:** `feat(chats): show the chats triggers start (MC-94)`.

---

## Final verification
From `backend/`:
```
megoocolab-runner services run test -- uv run pytest -q -n auto
megoocolab-runner services run migrate -- bash -c "uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head"
```
From `frontend/`:
```
npm run gen:api   # no diff in src/lib/api-types.ts
npx tsc --noEmit
npx eslint src/lib/triggers.ts src/components/triggers src/components/chats "src/app/(app)/projects/[key]"
npm test
megoocolab-runner services run e2e -- npx playwright test --reporter=line
```
Then check by hand on the e2e stack:
1. As a manager, create a "A task is finished" trigger for bugs.
2. Move a bug to Done. Within about 5 s, a chat titled `<name> · KEY-n` appears with the Trigger chip, its first message and the What happened block.
3. After the agent replies, the chat is ended.
4. The firing shows "Replied" on the trigger page.

## Requirements to steps
| Requirement | Step |
|---|---|
| The nine events | 2–6 |
| Loop guard | 4, used again in 5 |
| Savepoint | 4 |
| Firing rows and the loop | 1, 8 |
| Agent choice, skips, the hourly limit and its single notification | 8 |
| What happened | 2–3 (text), 9 (delivery) |
| End after the reply, `keep_open`, questions and failures, the notification switches | 10 |
| "Runs as", rights, validation codes, broken references, pause, resume and delete on closed projects | 11 |
| Try it | 12 |
| `ChatOut.trigger` | 7 |
| UI | 13–16 |
