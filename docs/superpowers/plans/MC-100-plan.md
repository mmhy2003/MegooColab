# MC-100 implementation plan: offer bug tasks for known failing tests found at finish

**Goal:** next to each `base` or `flaky` failing test in the workflow panel, a person with write access clicks **Create bug task** and gets an unassigned bug for that test. A test that already has an open bug in the project shows a link to that bug instead of the button.

**Architecture:** a new nullable column `tasks.failing_test` holds a normalised match key (`known_bugs.test_key`). A new module `backend/app/workflow/known_bugs.py` (same shape as `follow_ups.py`) finds open bugs by key (`open_bugs`) and creates one under a project row lock (`create`). A new endpoint `POST /api/tasks/{key}/workflow/known-failures/bug` calls it. `GET /api/tasks/{key}/workflow` fills `finish_tests.failures[].bug` with one query. On the frontend, `FinishFailures` renders the link or the button. `WorkflowPanel` and `EscalationActions` pass `onCreateBug` only when the panel is not `disabled`. `ActivityThread` renders the new event `finish.bug_created`.

## Conventions for every step

- Branch `megoo/MC-100-offer-bug-tasks-for-known-failing-tests` (already checked out). One commit per step. The subject is `type(area): what changed (MC-100)` (AGENTS.md "Commits"). The body says why, then ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never commit `.megoocolab/`, and never add plan or design files to `docs/`.
- TDD: write the test, run it and watch it fail, implement, then run it again and watch it pass.
- Backend commands run from `backend/`: `megoocolab-runner services run test -- uv run pytest <paths> -q`. Never run two pytest commands at once. Before each backend commit, run the step's files plus `tests/workflow tests/mcp tests/core/test_migrations.py -q -n auto`.
- Frontend commands run from `frontend/`: `npx vitest run <files>`, then `npx tsc --noEmit`, `npx eslint <changed files>` and `npm test`. Run `npm ci` first if `node_modules` is missing. Don't reformat files you don't otherwise change.
- Migrations run from `backend/`: `megoocolab-runner services run migrate -- bash scripts/makemigration.sh "<message>"`. Check down and up with `megoocolab-runner services run migrate -- bash -c "uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head"`.
- Agent-written text (test names, commands) is plain text in the UI and in titles, and a code span (`app.kb.filing._code_span`) in Markdown descriptions.
- **Never import the name `test_key` into a test module.** pytest would collect it as a test. Use `known_bugs.test_key(...)`.

### Names shared across steps

| Thing | Name |
| --- | --- |
| Column | `Task.failing_test: Mapped[str \| None] = mapped_column(String(300))` |
| Index | `ix_tasks_project_failing_test` on `(project_id, failing_test)` `WHERE failing_test IS NOT NULL` |
| Module | `app/workflow/known_bugs.py`: `OFFERED = ("base", "flaky")`, `test_key`, `open_bugs`, `title`, `description`, `create` |
| Endpoint | `POST /api/tasks/{key}/workflow/known-failures/bug`, body `KnownFailureBugIn {name}`, answer `WorkflowOut` |
| Error | 409 `failure_not_listed` |
| Schema | `KnownBugOut {key, title}`; `FinishFailureOut.bug: KnownBugOut \| None = None` |
| Event | `finish.bug_created`, data `{key, title, task_id, name, kind}`, actor the person |
| Frontend props | `FinishFailures`: `taskKey?`, `onCreateBug?: (name: string) => void`, `busy?`; `EscalationActions`: `taskKey?`, `onCreateBug?` |

## File map

| File | Change |
| --- | --- |
| `backend/app/tasks/models.py` | the `failing_test` column and its partial index |
| `backend/migrations/versions/<rev>_task_failing_test.py` | generated migration |
| `backend/app/workflow/known_bugs.py` | new: match key, open-bug lookup, bug text, create |
| `backend/app/workflow/schemas.py` | `KnownBugOut`, `FinishFailureOut.bug`, `KnownFailureBugIn` |
| `backend/app/workflow/router.py` | `_finish_tests` fills `bug`; the new endpoint |
| `backend/tests/workflow/test_known_bugs.py` | new: the backend tests |
| `backend/tests/workflow/test_finish_failures.py` | `test_workflow_api_returns_finish_tests` expects `"bug": None` on each row |
| `frontend/src/lib/api-types.ts` | regenerated (`npm run gen:api`) |
| `frontend/src/components/workflow/FinishFailures.tsx` | a second line on each row: the kind chip and the link or button |
| `frontend/src/components/workflow/EscalationActions.tsx` | passes `taskKey`, `onCreateBug`, `busy` on |
| `frontend/src/components/workflow/WorkflowPanel.tsx` | `onCreateBug`, passed to all three places |
| `frontend/src/components/task/ActivityThread.tsx` | the `finish.bug_created` line |
| tests under `frontend/src/components/{workflow,task}/__tests__/` | tests |
| `frontend/e2e/workflow.spec.ts` | a known failure in the accepted finish; click, link, board |

## Reference code

### R1: `backend/app/workflow/known_bugs.py`

Step 2 writes up to and including `open_bugs`. Step 3 adds the rest.

```python
"""Bug tasks for the known failing tests a finish reported (MC-100): a person asks for one per test from the
workflow panel, and a test that already has an open bug in the project links to it instead. One bug per test,
matched on `tasks.failing_test`. Workflow runs never create them (as follow_ups)."""

import re
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select

from app.auth.models import User
from app.kb.filing import _code_span
from app.projects.models import BoardColumn, ColumnCategory, Project
from app.tasks.models import LinkKind, Task, TaskLink, TaskType
from app.tasks.schemas import TaskCreate
from app.tasks.service import create_task, task_changed
from app.tasks.visibility import on_board
from app.workflow import engine
from app.workflow.follow_ups import _chat, task_path
from app.workflow.models import Stage, TaskWorkflow, WorkflowTestRun

OFFERED = ("base", "flaky")
# ":42" or ":42:5" right after a file extension: Playwright's position, which moves when the file is edited above it
_POSITION = re.compile(r"(\.[A-Za-z0-9]{1,10}):\d+(?::\d+)?(?!\w)")


def test_key(name: str) -> str:
    """The match key of a reported test name: whitespace collapsed, a position after a file name removed."""
    return _POSITION.sub(r"\1", " ".join(name.split()))


async def open_bugs(db, project_id: uuid.UUID, keys) -> dict[str, Task]:
    """The open bug of each key: on the board, not in a Done column. Of several, the lowest number."""
    keys = set(keys)
    if not keys:
        return {}
    rows = await db.execute(
        select(Task).join(BoardColumn, BoardColumn.id == Task.column_id)
        .where(Task.project_id == project_id, Task.failing_test.in_(keys), on_board(),
               BoardColumn.category != ColumnCategory.done)
        .order_by(Task.number)
    )
    found: dict[str, Task] = {}
    for t in rows.scalars():
        found.setdefault(t.failing_test, t)
    return found


def _409(code: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, code)


def title(name: str, kind: str) -> str:
    return f"{'Flaky' if kind == 'flaky' else 'Failing'} test: {' '.join(name.split())}"


def description(*, name: str, kind: str, source: str, start_branch: str | None, seen_on: str,
                command: str | None) -> str:
    """`source`: Markdown naming where it was seen (a task link, or the chat). Agent-written text is in code spans."""
    branch = _code_span(start_branch) if start_branch else "the start branch"
    if kind == "base":
        lead = f"This test already failed on the commit that {source} started from, on {branch}."
        kind_text = f"also fails on {branch}"
    else:
        lead = f"This test failed and then passed when it was run again at the finish of {source}."
        kind_text = "flaky"
    lines = [lead, "", f"- Test: {_code_span(name)}", f"- Kind: {kind_text}", f"- Seen at: {source}, {seen_on}"]
    if command:
        lines.append(f"- Command: {_code_span(command)}")
    return "\n".join(lines)


async def _command(db, task_id: uuid.UUID, name: str) -> str | None:
    """The command of the newest test run the task recorded at finish (not on the start commit) that failed the test."""
    rows = await db.execute(
        select(WorkflowTestRun)
        .where(WorkflowTestRun.task_id == task_id, WorkflowTestRun.stage == Stage.done,
               WorkflowTestRun.on_base.is_(False))
        .order_by(WorkflowTestRun.created_at.desc(), WorkflowTestRun.id.desc())
    )
    return next((r.command for r in rows.scalars() if name in (r.failing or [])), None)


async def create(db, user: User, project: Project, task: Task, name: str) -> None:
    """The bug for a known failing test the task's finish listed, unless the project has an open one already:
    unassigned, in the first before-work column, no epic, linked to the task and recorded on it. A chat round's
    bug gets no link and points back at the chat."""
    wf = await db.get(TaskWorkflow, task.id)
    failures = ((wf.finish_tests if wf is not None else None) or {}).get("failures") or []
    failure = next((f for f in failures if f.get("name") == name and f.get("kind") in OFFERED), None)
    if failure is None:
        raise _409("failure_not_listed")
    key = test_key(name)
    # one open bug per test in the project: a concurrent click, on this task or another, waits here and then sees it
    await db.execute(select(Project.id).where(Project.id == project.id).with_for_update())
    if await open_bugs(db, project.id, [key]):
        return
    chat = await _chat(db, task)
    source = (f"a round of the chat [{chat.title}](/chats/{chat.id})" if chat is not None
              else f"[{project.key}-{task.number}]({task_path(project.key, task.number)})")
    bug = await create_task(db, user, project, TaskCreate(
        title=title(name, failure["kind"]), type=TaskType.bug,
        description_md=description(name=name, kind=failure["kind"], source=source, start_branch=task.start_branch,
                                   seen_on=datetime.now(UTC).date().isoformat(),
                                   command=await _command(db, task.id, name)),
    ))
    bug.failing_test = key
    await task_changed(db, bug, "task.created")  # live boards show it
    if chat is None:
        db.add(TaskLink(source_id=task.id, target_id=bug.id, kind=LinkKind.relates))
    await engine.record_workflow_event(db, task, user.id, "finish.bug_created", {
        "key": f"{project.key}-{bug.number}", "title": bug.title, "task_id": str(bug.id),
        "name": name, "kind": failure["kind"],
    })
```

### R2: test helpers at the top of `backend/tests/workflow/test_known_bugs.py`

```python
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.auth.models import Role
from app.core.db import SessionLocal
from app.projects.models import BoardColumn, ColumnCategory
from app.tasks.models import Task, TaskLink
from app.workflow import known_bugs
from app.workflow.models import Stage, TaskWorkflow, WorkflowStatus, WorkflowTestRun
from tests.factories import login, make_project, make_user
from tests.workflow.test_engine import _events

BASE = {"name": "e2e/a.spec.ts:42:5 › finishes a task", "kind": "base"}
FLAKY = {"name": "tests/x.py::test_y", "kind": "flaky"}
NEW = {"name": "e2e/b.spec.ts:3", "kind": "new"}


async def _task(client, title="Pay out", project="PAY") -> dict:
    r = await client.post(f"/api/projects/{project}/tasks", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()


async def _finished(task: dict, failures, *, start_branch="develop") -> None:
    """The task's finish settled with these failures (as finish._settle_delivered leaves it)."""
    tid = uuid.UUID(task["id"])
    async with SessionLocal() as s:
        wf = await s.get(TaskWorkflow, tid) or TaskWorkflow(task_id=tid)
        wf.stage, wf.status = Stage.done, WorkflowStatus.finished
        wf.finish_tests = {"failures": failures, "failing_total": None, "diagnosis": None, "delivered": True,
                           "settled": "known"}
        s.add(wf)
        await s.execute(update(Task).where(Task.id == tid).values(start_branch=start_branch))
        await s.commit()


async def _bugs() -> list[Task]:
    async with SessionLocal() as s:
        rows = await s.execute(select(Task).where(Task.failing_test.is_not(None)).order_by(Task.number))
        return list(rows.scalars())


async def _to_done(task_id) -> None:
    async with SessionLocal() as s:
        t = await s.get(Task, task_id)
        t.column_id = await s.scalar(select(BoardColumn.id).where(
            BoardColumn.project_id == t.project_id, BoardColumn.category == ColumnCategory.done))
        await s.commit()


def _create(client, key, name):
    return client.post(f"/api/tasks/{key}/workflow/known-failures/bug", json={"name": name})
```

`make_project(client, db, "PAY", *members)` (tests/factories.py) creates a team with a new manager plus the members and a project. It leaves `client` logged in as that manager and returns `(project_json, manager, team)`. For a read-only person: `viewer = await make_user(db, role=Role.viewer)`, passed as a member, then `await login(client, viewer)`.

### R3: step 3's tests (in test_known_bugs.py)

Each test finishes a task with `_finished(t, [NEW, BASE, FLAKY])` and calls `await _create(client, t["key"], name)`.

- `test_creates_a_bug_for_a_base_failure`: the answer is 200, and there is one bug with:
  - type `bug`, `assignee_user_id`/`assignee_agent_id` None, `parent_id` None, `reporter_id` the manager;
  - the column: the project's first `before` column (lowest position);
  - title `"Failing test: e2e/a.spec.ts:42:5 › finishes a task"` and `failing_test == "e2e/a.spec.ts › finishes a task"`;
  - a description equal to `known_bugs.description(name=BASE["name"], kind="base", source=f"[PAY-{n}](/projects/PAY/tasks/{n})", start_branch="develop", seen_on=datetime.now(UTC).date().isoformat(), command=None)`, which starts with ``This test already failed on the commit that [PAY-1](/projects/PAY/tasks/1) started from, on `develop`.`` and has no `- Command:` line;
  - a `TaskLink` with kind `relates` from the task to the bug;
  - one `finish.bug_created` event on the task (`_events(task_id, "finish.bug_created")`), with `actor_user_id` the manager and data `{key, title, task_id, name: BASE["name"], kind: "base"}`.
- `test_flaky_title_and_command_line`: add `WorkflowTestRun` rows for the task, in this order:
  - `stage="done"`, `command="pytest -x"`, failing `[FLAKY name]`, passed False;
  - a newer one with `command="make test"` and the name;
  - a newest one with `on_base=True` and `command="base run"`;
  - one with `stage="build"`.

  Set `created_at` explicitly so the order holds. The bug's title is `"Flaky test: tests/x.py::test_y"`. Its description starts with `This test failed and then passed when it was run again at the finish of [PAY-` and contains ``- Command: `make test` ``. A second task with `_finished(t2, [BASE], start_branch=None)` gets `on the start branch.` in its description.
- `test_no_duplicates`:
  - Click BASE twice: one bug, one event.
  - A second task of PAY finished with `[{"name": "e2e/a.spec.ts:57:5 › finishes a task", "kind": "base"}]` clicks it: 200, still one bug in PAY, and no event on the second task.
  - `await make_project(client, db, "SHOP")`, then a SHOP task with `[BASE]` clicks it: SHOP gets its own bug, two bugs in total.
- `test_offered_again_after_done_or_delete`: `_to_done(bug.id)`, then click again, which makes a second bug. Delete that one with `await client.delete(f"/api/tasks/{key}")`. A click then makes a third. While none is open, every click creates exactly one.
- `test_refusals`:
  - the `NEW` name gives 409 `failure_not_listed`;
  - `"no such test"` gives 409;
  - a task without a workflow gives 409;
  - after `login(client, viewer)`, BASE gives 403 `forbidden`.

  Nothing is created.
- `test_the_task_itself_is_the_bug`: set the task's own `failing_test = known_bugs.test_key(FLAKY["name"])`, finish it with `[FLAKY]`, click: 200, and no task is created.
- `test_chat_round(client, db)`: set up as `test_chat_round_follow_ups` in `tests/workflow/test_follow_ups.py` does (`world`, `start` from `tests.chats.helpers`, `_round` from `tests.chats.test_chat_workflow`). Then `_finished({"id": str(rnd.id)}, [BASE])` and click with the key `chat["rounds"][0]["key"]`. The bug has `chat_id` None and `in_chat` False, there is no `TaskLink` with `source_id == rnd.id`, and its description contains `f"(/chats/{chat['id']})"`.

### R4: `FinishFailures` row (step 5)

```tsx
<li key={`${i}-${f.name}`}>
  <code className="break-all">{f.name}</code>
  <div className="mt-0.5 flex flex-wrap items-center gap-2">
    <span className="rounded border px-1 text-muted-foreground">{failureKindLabel(f.kind, startBranch)}</span>
    {f.bug ? (
      f.bug.key === taskKey ? (
        <span className="text-muted-foreground">Bug: this task</span>
      ) : (
        <Link href={bugHref(f.bug.key)} title={f.bug.title} className="text-cyan-ink underline">Bug: {f.bug.key}</Link>
      )
    ) : (
      onCreateBug && f.kind !== "new" && (
        <Button variant="ghost" disabled={busy} onClick={() => onCreateBug(f.name)}>Create bug task</Button>
      )
    )}
  </div>
</li>
```

At module level: `const bugHref = (key: string) => \`/projects/${key.replace(/-\d+$/, "")}/board?task=${key}\`;` (the same href as `ActivityThread`'s `taskHref`). Imports: `import Link from "next/link";` and `import { Button } from "@/components/ui/Button";`.

## Steps

1. Add the tasks.failing_test column, its partial index and the migration
2. known_bugs: the match key and the open-bug lookup
3. known_bugs.create and POST /api/tasks/{key}/workflow/known-failures/bug
4. The workflow API carries the open bug on each base and flaky row
5. FinishFailures: a link to the open bug, or a Create bug task button
6. WorkflowPanel and EscalationActions offer Create bug task to people who can edit
7. The activity thread shows finish.bug_created
8. End to end: a known failure at finish gets a bug task

Each step's full detail is in its subtask. The reference code above is shared between them.

## Final verification

From `backend/`:

- `megoocolab-runner services run test -- uv run pytest tests/workflow tests/mcp tests/core/test_migrations.py tests/tasks -q -n auto`
- `megoocolab-runner services run migrate -- bash -c "uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head"`

From `frontend/`:

- `npm test`, `npx tsc --noEmit`, `npx eslint src/components/workflow src/components/task e2e/workflow.spec.ts`
- `megoocolab-runner services run e2e -- npx playwright test --reporter=line`

## Requirement coverage

| Design requirement | Step |
| --- | --- |
| `tasks.failing_test` and its index, not in TaskCreate/TaskUpdate/TaskOut/MCP | 1 |
| `test_key` normalisation | 2 |
| Open = not in Done, not a chat round; the lowest number wins | 2 |
| Endpoint, `failure_not_listed`, lock, no duplicate, title, description, Command line, link, event, no parent, chat round, read-only and closed project (existing `get_task_for(write=True)`) | 3 |
| `bug` on GET rows; the task that is itself the bug | 4 |
| Link or button; `new` rows never get the button; "this task" | 5 |
| All three places; hidden when `disabled`; busy; refresh after the click and on a 409 | 6 |
| Activity line | 7 |
| End to end | 8 |
