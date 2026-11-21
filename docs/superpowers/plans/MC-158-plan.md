# MC-158 plan: subtasks no longer send a Done notification

## Goal
A card of type `subtask` that enters Done tells nobody. Stories, tasks, bugs and epics notify as they do today.

## Architecture
`backend/app/tasks/service.py::notify_done` is the only place that sends `task_done` / `team_task_done`. Both callers go through it: `move_task` (a person or a chat's agent) and `workflow/engine.py::move_to_category` (the workflow). One early `return` for `task.type == TaskType.subtask`, next to the existing `task.in_chat` return, covers every caller and every channel. `TaskType` is already imported in that module. No schema, migration, API or frontend change.

## File map
| File | Change |
|---|---|
| `backend/app/tasks/service.py` | Guard plus a docstring clause in `notify_done` (line ~539) |
| `backend/app/notifications/models.py` | Comments on `Kind.task_done` / `Kind.team_task_done` (lines 20-21) say "a task (not a subtask)" |
| `backend/tests/notifications/test_task_done.py` | Module docstring gets one sentence; four new tests and a `_subtask` helper |

## Steps

### 1. Silence the Done notification for subtasks (TDD)

**Test first.** Add these to `backend/tests/notifications/test_task_done.py`. They use the helpers the file already imports (`_board`, `_member`, `_move`, `_workflow_moves`, `_done_rows`, `update`, `Task`, `uuid`). Put them after `test_a_chats_agent_moving_a_task_to_done_tells_its_owner` and before `test_defaults_and_email_look`:

```python
def _subtask(tc, parent_key_id: str, title: str = "Step 1") -> dict:
    r = tc.post("/api/projects/PAY/tasks", json={"title": title, "type": "subtask", "parent_id": parent_key_id})
    assert r.status_code == 201, r.text
    return r.json()


async def test_the_workflow_finishing_a_subtask_tells_nobody(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b = await _board(db, tc)
    member = await _member(db, tc)
    sub = _subtask(tc, b.task["id"])  # a plan step: no assignee, like the ones Build makes
    await _workflow_moves(uuid.UUID(sub["id"]), "done")
    assert await _done_rows(b.manager.id) == []
    assert await _done_rows(member.id) == []


async def test_a_person_moving_a_subtask_to_done_tells_nobody(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b = await _board(db, tc)
    member = await _member(db, tc)
    sub = _subtask(tc, b.task["id"])
    assert _move(tc, sub["key"], b.cols["done"]).status_code == 200
    assert await _done_rows(member.id) == []


async def test_a_subtask_assigned_to_a_person_does_not_tell_them(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b = await _board(db, tc)
    member = await _member(db, tc)
    sub = _subtask(tc, b.task["id"])
    await db.execute(update(Task).where(Task.id == uuid.UUID(sub["id"])).values(assignee_user_id=member.id))
    await db.commit()
    assert _move(tc, sub["key"], b.cols["done"]).status_code == 200  # the manager moves it
    assert await _done_rows(member.id) == []


async def test_the_parent_finishing_after_its_subtask_tells_each_person_once(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b = await _board(db, tc)
    member = await _member(db, tc)
    sub = _subtask(tc, b.task["id"])
    await _workflow_moves(uuid.UUID(sub["id"]), "done")
    await _workflow_moves(b.task_id, "done")
    [mine] = await _done_rows(b.manager.id)
    assert (mine.kind, mine.task_id) == ("task_done", b.task_id)
    [theirs] = await _done_rows(member.id)
    assert (theirs.kind, theirs.task_id) == ("team_task_done", b.task_id)
```

Also change the module docstring to:

```python
"""A task reaching Done: whoever it is assigned to (for an agent, its owner) hears it as task_done, everyone else on the
project's teams as team_task_done. Never the person who moved it; once per move into Done. A subtask reaching Done tells
nobody: its parent task stands for it."""
```

**Run, expect failure** (from `backend/`):
`megoocolab-runner services run test -- uv run pytest tests/notifications/test_task_done.py -q`
Expected: the first three new tests fail (a `team_task_done` / `task_done` row exists for the subtask); the fourth fails on the `[mine]` / `[theirs]` unpacking (two rows each). The six existing tests pass.

**Implement.** In `backend/app/tasks/service.py::notify_done`:

```python
async def notify_done(db: AsyncSession, task: Task, *, actor: User | None = None, agent: Agent | None = None) -> None:
    """The task moved into Done (from a column that isn't): its assignee (for an agent, the agent's owner) hears it as
    task_done, everyone else on the project's teams as team_task_done; never the person who moved it. A subtask tells
    nobody: its parent task stands for it. Moved by `actor` (a person), by `agent` (a chat's agent, with its owner's
    rights), or, with neither, by its workflow."""
    if task.in_chat:  # a chat's round: the chat itself is what the people concerned follow
        return
    if task.type == TaskType.subtask:  # a plan step or a hand-made subtask: only its parent's Done is news
        return
    ...unchanged...
```

In `backend/app/notifications/models.py` lines 20-21:

```python
    task_done = "task_done"  # a task (not a subtask) assigned to me or my agent moved into Done
    team_task_done = "team_task_done"  # any other task (not a subtask) of my teams' projects moved into Done
```

**Run, expect pass:** the same command: all 10 tests pass. Then run the related suites:
`megoocolab-runner services run test -- uv run pytest tests/notifications tests/tasks tests/workflow -q -n auto`. Expected: all pass.

**Commit:**
```
fix(notifications): a subtask reaching Done tells nobody

Every plan step is a subtask that the workflow moves to Done during Build, and each one sent "KEY is done" to the
whole team, so a task with eight steps sent nine notifications. notify_done now returns early for subtasks, whoever
moves them; the parent task's Done is still sent as before.
```

## Final verification
From `backend/`:
- `megoocolab-runner services run test -- uv run pytest tests/notifications/test_task_done.py -q`: 10 passed.
- `megoocolab-runner services run test -- uv run pytest -q -n auto`: the whole backend suite passes.
- `git diff --stat main`: only the three files in the file map changed.
