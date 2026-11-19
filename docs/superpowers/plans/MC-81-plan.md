# MC-81 implementation plan: follow-up tasks proposed with a design, created on approval

## Goal
A design can carry up to 10 proposed follow-up tasks. The person reviews them in the design approval view (untick, edit, add), and approving creates the ticked tasks, links them, records events and appends or replaces a scope note on the originating task's description.

## Architecture
- **Backend.** A new module `backend/app/workflow/follow_ups.py` holds everything specific to follow-ups: the two validators, the creation on approval, the scope note, and the REST helpers. `documents.submit` stores the agent's list in a new JSONB column `workflow_documents.follow_ups`. `documents.decide` takes the reviewed list from the approval request and calls `follow_ups.create_on_approval` inside the transaction it already runs in. The MCP tool `submit_design` gains an optional `follow_ups` argument. Role gates are unchanged.
- **Frontend.** A new `components/workflow/FollowUps.tsx` draws the block. `DocumentView` holds the review state and sends it with Approve. `MockupPanel` swaps "Approve this version" for "Review follow-up tasks (n)" when the pending design proposes any. `ActivityThread` renders the `follow_up_created` row.

## Conventions for every step
- Work on the current branch `megoo/MC-81-brainstorm-design-can-propose-follow-up`. Make one commit per step with the subject given in the step. The body says why and what in plain sentences and ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never commit `.megoocolab/`.
- TDD: write the test, run it and watch it fail, implement, then run it again.
- Backend tests always run through the services: `cd backend; megoocolab-runner services run test -- uv run pytest <files> -q`. Before committing, run the whole suite with `megoocolab-runner services run test -- uv run pytest -q -n auto`. Never start two pytest runs at once. Known pre-existing flaky or failing tests (search, rate-limit, dashboard timing) are not regressions.
- Frontend checks run from `frontend/`: `npx vitest run <file>`, then `npx tsc --noEmit`, `npx eslint <changed files>` and `npm test`. Don't run Prettier.
- **`frontend/src/lib/api-types.ts` is regenerated (`cd frontend; npm run gen:api`) only in step 9.** Backend steps 1 to 8 change the API but leave the generated types alone, so `tsc` stays green between steps.
- Error responses use `HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "<code>")`, the same as `documents._422`.

## File map
| File | Change |
|---|---|
| `backend/app/workflow/models.py` | `WorkflowDocument.follow_ups` (JSONB, not null, default `[]`) and `scope_note` (Text, nullable) |
| `backend/migrations/versions/<rev>_design_follow_ups.py` | new migration, generated |
| `backend/app/workflow/follow_ups.py` | **new**: `clean_proposed`, `clean_reviewed`, `backlink`, `scope_note`, `create_on_approval`, `earlier`, `entries_out`, `creates_in` |
| `backend/app/workflow/documents.py` | `submit(..., follow_ups=None)`, `submit_connect_only(..., follow_ups=None)`, `decide(..., follow_ups=None)` |
| `backend/app/workflow/schemas.py` | `FollowUpReviewIn`, `FollowUpOut`, `FollowUpRef`, `FollowUpPlace`; `DocumentInfo.follow_up_count`; `DocumentOut.follow_ups/earlier_follow_ups/creates_in`; `DocumentDecisionIn.follow_ups` |
| `backend/app/workflow/router.py` | passes the reviewed list to `decide`; fills the new output fields |
| `backend/app/mcp_server/workflow_tools.py` | `submit_design(key, markdown, follow_ups=None)` returns the count; `_submit` passes it through; `get_document` returns `follow_ups` |
| `backend/app/workflow/methodology_texts/defaults/brainstorm.md`, `design_revision.md` | the new argument and a "Follow-up tasks" part |
| `backend/app/workflow/methodology_history.py` | the two new hashes |
| `backend/tests/workflow/test_follow_ups.py` | **new** |
| `backend/tests/workflow/test_documents.py`, `tests/workflow/test_models.py`, `tests/mcp/test_workflow_tools.py`, `tests/workflow/test_methodology.py` | extended |
| `frontend/src/components/workflow/FollowUps.tsx` | **new**: the "Follow-up tasks" block |
| `frontend/src/components/workflow/DocumentView.tsx` | review state, the block, the line above Approve, the list sent with Approve |
| `frontend/src/components/workflow/MockupPanel.tsx` | the "Review follow-up tasks (n)" button |
| `frontend/src/components/task/ActivityThread.tsx` | the `follow_up_created` row |
| `frontend/src/lib/errors.ts`, `frontend/src/lib/types.ts`, `frontend/src/lib/api-types.ts` | error texts, type aliases, regenerated types |
| `frontend/src/components/workflow/__tests__/FollowUps.test.tsx` | **new** |
| `frontend/src/components/workflow/__tests__/DocumentView.test.tsx`, `MockupPanel.test.tsx`, `frontend/src/components/task/__tests__/ActivityThread.test.tsx` | extended |
| `frontend/e2e/workflow.spec.ts` | the design proposes two follow-ups; untick one, add one, approve |

## Reference code

### R1. Model columns (`backend/app/workflow/models.py`, in `WorkflowDocument` after `mockup_id`)
```python
    # designs: follow-up tasks for later phases, [{title, type, description_md, task_id}]; task_id is set when
    # approval creates the task (MC-81)
    follow_ups: Mapped[list] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, server_default=text("'[]'::jsonb")
    )
    # designs: the scope note this version's approval wrote into the task's description (MC-81)
    scope_note: Mapped[str | None] = mapped_column(Text)
```

### R2. `backend/app/workflow/follow_ups.py`: validation (step 2)
```python
"""Follow-up tasks a design proposes for the later phases of a split task (MC-81): checked when the agent submits
the design and when a person approves it, and created on approval. Workflow runs never create tasks themselves."""

from fastapi import HTTPException, status

from app.core.text import strip_nul
from app.tasks.models import TaskType

MAX_FOLLOW_UPS = 10
MAX_TITLE = 500
MAX_DESCRIPTION = 4_000
TYPES = frozenset({TaskType.story.value, TaskType.task.value, TaskType.bug.value})


def _422(code: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, code)


def _entry(item, *, reviewed: bool) -> dict:
    if not isinstance(item, dict):
        raise _422("invalid_follow_ups")
    title, kind, description = item.get("title", ""), item.get("type", "task"), item.get("description_md", "")
    if not all(isinstance(v, str) for v in (title, kind, description)) or kind not in TYPES:
        raise _422("invalid_follow_ups")
    title, description = strip_nul(title).strip(), strip_nul(description)
    entry = {"title": title, "type": kind, "description_md": description, "task_id": None}
    if reviewed:
        create = item.get("create")
        if not isinstance(create, bool):
            raise _422("invalid_follow_ups")
        entry["create"] = create
    if not title and (not reviewed or entry["create"]):
        raise _422("invalid_follow_ups")
    if len(title) > MAX_TITLE or len(description) > MAX_DESCRIPTION:
        raise _422("too_large")
    return entry


def _list(items) -> list:
    if not isinstance(items, list) or len(items) > MAX_FOLLOW_UPS:
        raise _422("invalid_follow_ups")
    return items


def clean_proposed(items) -> list[dict]:
    """What the agent passed to submit_design. None (left out) proposes none."""
    if items is None:
        return []
    return [_entry(i, reviewed=False) for i in _list(items)]


def clean_reviewed(items) -> list[dict]:
    """What the person sent with the approval: the whole list in order, each with `create`. An unticked row the
    person left without a title is dropped."""
    entries = [_entry(i, reviewed=True) for i in _list(items)]
    return [e for e in entries if e["title"]]
```

### R3. Creation on approval (step 4; extended in steps 5 and 6)
Added imports: `import uuid`, `from sqlalchemy import select`, `from app.auth.models import User`, `from app.projects.models import Project`, `from app.tasks.models import LinkKind, Task, TaskLink`, `from app.tasks.schemas import TaskCreate`, `from app.tasks.service import create_task, record_event, task_changed`, `from app.workflow.models import WorkflowDocument`.
```python
def task_path(project_key: str, number: int) -> str:
    return f"/projects/{project_key}/tasks/{number}"


def backlink(project_key: str, number: int, version: int) -> str:
    """The line that ends a created task's description: where it came from."""
    path = task_path(project_key, number)
    return (f"Follow-up of [{project_key}-{number}]({path}), from its "
            f"[approved design (v{version})]({path}#document-design-v{version}).")


async def _epic_id(db, task: Task) -> uuid.UUID | None:
    if task.parent_id is None:
        return None
    parent = await db.get(Task, task.parent_id)
    return parent.id if parent is not None and parent.type == TaskType.epic else None


async def create_on_approval(db, user: User, task: Task, doc: WorkflowDocument, reviewed: list[dict]) -> None:
    """Create the ticked entries of the approved design, in order: unassigned, in the first before-work column,
    in the task's epic, each linked to the task and recorded on it. The approved version keeps the reviewed list,
    with the created tasks' ids. Runs inside decide's transaction: a failure undoes the approval too."""
    project = await db.get(Project, task.project_id)
    epic_id = await _epic_id(db, task)
    tail = backlink(project.key, task.number, doc.version)
    entries, created = [], []
    for item in reviewed:
        entry = {"title": item["title"], "type": item["type"], "description_md": item["description_md"],
                 "task_id": None}
        if item["create"]:
            new = await create_task(db, user, project, TaskCreate(
                title=item["title"], type=TaskType(item["type"]),
                description_md=f"{item['description_md'].rstrip()}\n\n{tail}".lstrip(), parent_id=epic_id,
            ))
            await task_changed(db, new, "task.created")  # live boards show it
            db.add(TaskLink(source_id=task.id, target_id=new.id, kind=LinkKind.relates))
            await record_event(db, task, user.id, "follow_up_created", {
                "key": f"{project.key}-{new.number}", "title": new.title, "task_id": str(new.id),
                "type": str(new.type), "design_version": doc.version,
            })
            entry["task_id"] = str(new.id)
            created.append(new)
        entries.append(entry)
    doc.follow_ups = entries  # a new list: edits inside nested dicts are not tracked
    if created:
        await _write_scope_note(db, user, project, task, doc, created)   # step 5
```
In step 4 the last two lines are left out; step 5 adds them.

### R4. Scope note (step 5)
Added imports: `from app.tasks.schemas import TaskUpdate`, `from app.tasks.service import update_task`, `from app.workflow.models import DocKind, DocStatus`.
```python
def scope_note(phases: list[tuple[str, str]], design_link: str) -> str:
    """`phases`: (key, path) of every follow-up task, in order. This task is phase 1."""
    total = len(phases) + 1
    links = ", ".join(f"[{key}]({path})" for key, path in phases)
    later = "Phase 2" if total == 2 else f"Phases 2–{total}"   # an en dash
    return f"Scope: phase 1 of {total} (per the [approved design]({design_link})). {later} → {links}."


def _other_approved(task: Task, doc: WorkflowDocument):
    return (WorkflowDocument.task_id == task.id, WorkflowDocument.kind == DocKind.design,
            WorkflowDocument.status == DocStatus.approved, WorkflowDocument.id != doc.id)


async def earlier(db, task: Task, doc: WorkflowDocument) -> list[Task]:
    """Follow-up tasks the task's other approved design versions created and that still exist, oldest first."""
    lists = (await db.execute(select(WorkflowDocument.follow_ups).where(*_other_approved(task, doc))
                              .order_by(WorkflowDocument.version))).scalars()
    ids = [uuid.UUID(e["task_id"]) for entries in lists for e in (entries or []) if e.get("task_id")]
    if not ids:
        return []
    found = {t.id: t for t in (await db.execute(select(Task).where(Task.id.in_(ids)))).scalars()}
    return [found[i] for i in ids if i in found]


async def _write_scope_note(db, user, project, task, doc, created: list[Task]) -> None:
    phases = [(f"{project.key}-{t.number}", task_path(project.key, t.number))
              for t in [*await earlier(db, task, doc), *created]]
    design_link = f"{task_path(project.key, task.number)}#document-design-v{doc.version}"
    note = scope_note(phases, design_link)
    previous = await db.scalar(
        select(WorkflowDocument.scope_note)
        .where(*_other_approved(task, doc), WorkflowDocument.scope_note.is_not(None))
        .order_by(WorkflowDocument.version.desc()).limit(1)
    )
    current = task.description_md or ""
    if previous and previous in current:  # the note the system wrote before, unedited: replace its last copy
        i = current.rindex(previous)
        text = current[:i] + note + current[i + len(previous):]
    else:
        text = f"{current.rstrip()}\n\n{note}" if current.strip() else note
    # a normal description change: field_changed is recorded and the memory update is queued
    await update_task(db, user, project, task, TaskUpdate(description_md=text))
    doc.scope_note = note
```
Step 6 changes `design_link` and the backlink for chat rounds (see step 6).

### R5. Schemas (`backend/app/workflow/schemas.py`)
Step 4 adds the input:
```python
class FollowUpReviewIn(BaseModel):
    """One row of the reviewed follow-up list sent with a design approval (MC-81); checked by the service."""
    title: NoNulStr = ""
    type: str = "task"
    description_md: NoNulStr = ""
    create: bool

# in DocumentDecisionIn:
    follow_ups: list[FollowUpReviewIn] | None = None  # a design approval: the whole reviewed list, in order
```
Step 7 adds the output:
```python
class FollowUpOut(BaseModel):
    title: str
    type: str
    description_md: str
    created: bool
    task_key: str | None  # None when not created, or created and deleted since


class FollowUpRef(BaseModel):
    key: str
    title: str


class FollowUpPlace(BaseModel):
    column: str
    epic: FollowUpRef | None

# DocumentInfo:
    follow_up_count: int = 0  # designs: how many follow-up tasks the version proposes
# DocumentOut:
    follow_ups: list[FollowUpOut] = []
    earlier_follow_ups: list[FollowUpRef] = []  # what earlier approved versions created
    creates_in: FollowUpPlace | None = None  # a submitted design: where approving would create the tasks
```

### R6. `decide` changes (step 4)
```python
from app.workflow.follow_ups import clean_reviewed, create_on_approval

async def decide(db, user, task, kind, version, approve, comment, images=(), follow_ups: list[dict] | None = None):
    ...
    if not approve and not comment:
        raise _422("comment_required")
    # checked before anything is written; a rejection or a plan ignores the list
    reviewed = clean_reviewed(follow_ups) if approve and kind == DocKind.design and follow_ups is not None else None
    doc = ...                                   # unchanged
    ...already_decided / not_waiting_for_decision checks (unchanged)...
    if approve and kind == DocKind.design and doc.follow_ups and reviewed is None:
        raise _422("follow_ups_required")      # a page that never showed the list
    ...status, events, audit, filing (unchanged)...
    elif kind == DocKind.design:
        if reviewed is not None:
            await create_on_approval(db, user, task, doc, reviewed)
        await engine.set_stage(db, wf, task, Stage.plan)
        ...
```
Router:
```python
    await documents.decide(
        db, user, task, kind, version, body.approve, body.comment, [] if body.approve else body.image_ids,
        follow_ups=None if body.follow_ups is None else [f.model_dump() for f in body.follow_ups],
    )
```

### R7. `FollowUps.tsx` contract (step 9)
```ts
export type FollowUpType = "story" | "task" | "bug";
export type FollowUpRow = { title: string; type: FollowUpType; description_md: string; create: boolean; added: boolean };
export const MAX_FOLLOW_UPS = 10;

/** The rows a review starts from: every proposed entry, ticked. */
export function initialRows(detail: DocumentDetail): FollowUpRow[];

export function FollowUps(props: {
  detail: DocumentDetail;
  projectKey: string;                       // for links: /projects/<projectKey>/board?task=<key>
  review?: { rows: FollowUpRow[]; onChange: (rows: FollowUpRow[]) => void };
}): JSX.Element | null;
```
Accessible names (tests and the e2e spec rely on them; n is the 1-based row number):
- the block: `<section aria-label="Follow-up tasks">` with a heading "Follow-up tasks";
- checkbox `Create task n`; select `Type of task n` (options story, task, bug); input `Title of task n`; a `<details>` whose summary reads "Description" containing a textarea `Description of task n` (maxLength 4000); title maxLength 500;
- rows the person added show the text "added by you" and a button `Remove task n`;
- button "+ Add a task" appends `{title: "", type: "task", description_md: "", create: true, added: true}`, disabled at 10 rows;
- an empty review list shows "None proposed.";
- `earlier_follow_ups` non-empty: "Already created from an earlier approved design: " followed by the keys as links, comma-separated, then ".";
- read-only (no `review`): returns null when `follow_ups` and `earlier_follow_ups` are both empty. Otherwise one list item per entry: `<type> · <title>`, the description in a `<details>`. On an approved version, a created entry with a `task_key` shows "created " and the key as a link. A created entry without one shows "created" with no link. An entry that wasn't created shows "not created".

## Steps

### Step 1. Store follow-ups on design documents
See the step's detail.

### Step 2. Validate and store the proposed follow-ups when a design is submitted
See the step's detail.

### Step 3. submit_design takes follow_ups and get_document returns them
See the step's detail.

### Step 4. Approving a design creates the ticked follow-up tasks
See the step's detail.

### Step 5. Approval writes or replaces the scope note on the originating task
See the step's detail.

### Step 6. Follow-ups from a chat round link back to the chat
See the step's detail.

### Step 7. The document API shows follow-ups, earlier tasks and where they go
See the step's detail.

### Step 8. The brainstorm and revision instructions teach follow-ups
See the step's detail.

### Step 9. The FollowUps block in the frontend
See the step's detail.

### Step 10. The design approval view reviews and sends the follow-ups
See the step's detail.

### Step 11. Mockup panel button and the follow_up_created activity row
See the step's detail.

### Step 12. Browser test: review and create follow-ups end to end
See the step's detail.

(Each step's full detail is the matching entry of the `steps` array, and the code it refers to is under "Reference code" above.)

## Final verification
```bash
cd backend
megoocolab-runner services run test -- uv run pytest -q -n auto
megoocolab-runner services run migrate -- bash -c "uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head"
cd ../frontend
npx tsc --noEmit
npx eslint src/components/workflow src/components/task/ActivityThread.tsx src/lib/errors.ts src/lib/types.ts e2e/workflow.spec.ts
npm test
megoocolab-runner services run e2e -- npx playwright test e2e/workflow.spec.ts e2e/mockups.spec.ts --reporter=line
```
Every requirement maps to a step:
- proposal on `submit_design` with a per-version list: steps 2 and 3;
- review (untick, edit, add): steps 9 and 10;
- creation on approval (unassigned, first column, epic, backlink, relates link, event): step 4;
- scope note (append or replace, a `field_changed` event): step 5;
- rejected and superseded versions create nothing: step 4 tests;
- chat rounds: step 6;
- the earlier-tasks line and the column and epic line: steps 7 and 10;
- the mockup button: step 11;
- the activity row: step 11;
- methodology texts: step 8;
- the browser test: step 12.
