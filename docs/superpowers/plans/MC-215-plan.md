# MC-215 plan: build the Knowledge Base and Memory sections after the commit

## Goal
No embedding call is made while a task, workflow or run row is locked: `enqueue` builds the prompt from DB reads only, and the Knowledge Base and Memory sections are added after the commit, in `dispatch_pending`, before the run can be claimed.

## Architecture
`app/workflow/context.py` gets a second provider list, `late_providers`, and `late_sections()`. The KB and Memory providers register there instead of in `context_providers`, so `build_prompt` (unchanged) no longer calls them. `enqueue` stores `AgentRun.context_at = len(prompt)` (before the resume note). A new module, `app/agent_runs/late_context.py`, has `fill_pending(owner_id)`. It reads in sessions of its own, with no row locks, inserts the sections at the mark, and writes them with one conditional UPDATE. `dispatch_pending` calls it first, and `_claim_next` never claims a marked run.

## Conventions for every step
- Run backend commands from `backend/`. Tests: `megoocolab-runner services run test -- uv run pytest <paths> -q`. Never run two pytest commands at once. Before each commit, also run `megoocolab-runner services run test -- uv run pytest tests/workflow tests/mcp -q -n auto`.
- Lint the changed files: `uvx ruff check --select E9,F <files>`.
- Commits: one per step, `type(area): sentence (MC-215)`. The body says why and what, and ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Nothing from `.megoocolab/` is committed.
- Service functions never commit; loops, routers and `fill_pending` (it owns its sessions) do.
- An import that would make a cycle is written inside the function, with a `# local:` comment.

## File map
| File | Change |
|---|---|
| `backend/app/agent_runs/models.py` | new column `context_at: Mapped[int \| None]` |
| `backend/migrations/versions/<rev>_agent_run_context_at.py` | new: adds `agent_runs.context_at INTEGER NULL` |
| `backend/tests/agent_runs/test_context_at_migration.py` | new: migration test |
| `backend/app/workflow/context.py` | `late_providers`, `late_sections()`; comments |
| `backend/app/agent_runs/late_context.py` | new: `insert_sections()`, `fill_pending()` |
| `backend/tests/agent_runs/test_late_context.py` | new: fill, claim and dispatch tests |
| `backend/app/agent_runs/service.py` | `dispatch_pending` calls `fill_pending` first; `_claim_next` skips marked runs |
| `backend/app/kb/context.py`, `backend/app/memory/context.py` | `register()` appends to `late_providers` |
| `backend/app/workflow/engine.py` | `enqueue` sets `context_at`; line in the lock order docstring |
| `backend/tests/workflow/test_prompt_locks.py` | new: acceptance tests and enqueue tests |
| `backend/tests/kb/test_context.py`, `backend/tests/kb/test_review_fixes.py`, `backend/tests/memory/test_context.py` | updated for `late_providers` |

## Shared code

### A. `backend/app/agent_runs/late_context.py` (step 2)
```python
"""The Knowledge Base and Memory sections of a queued workflow run's prompt, added after the commit that queued it
(MC-215).

`enqueue` builds the prompt from DB reads only, under the task, workflow and run locks, and marks where these
sections go (`AgentRun.context_at`). Their providers may wait seconds on an AI provider, so they run here, from
`dispatch_pending`, with no row lock held. The run is never claimed while it is marked (`_claim_next`)."""

import logging
import uuid

from sqlalchemy import select, update

from app.agent_runs.models import AgentRun, RunStatus
from app.agents.models import Agent
from app.core.db import SessionLocal
from app.tasks.models import Task
from app.workflow import context as wf_context
from app.workflow.models import RunRole

log = logging.getLogger(__name__)


def insert_sections(prompt: str, at: int, sections: list[str]) -> str:
    """`sections` placed at `at`, each after a blank line, in order, while the prompt stays within
    MAX_PROMPT_CHARS: a section that does not fit is left out, and so are those after it."""
    room = wf_context.MAX_PROMPT_CHARS - len(prompt)
    added = ""
    for section in sections:
        part = "\n\n" + section
        if len(added) + len(part) > room:
            break
        added += part
    return prompt[:at] + added + prompt[at:]


async def _fill(run_id: uuid.UUID) -> None:
    async with SessionLocal() as s:  # reads only: no row lock is held while the providers wait
        run = await s.get(AgentRun, run_id)
        if run is None or run.status != RunStatus.queued or run.context_at is None:
            return
        task = await s.get(Task, run.task_id)
        if task is None:
            return
        sections = await wf_context.late_sections(s, task, RunRole(run.workflow_role))
        prompt = insert_sections(run.prompt, run.context_at, sections)
        # the run row alone, for one statement (lock 3 of the engine's order); a run cancelled meanwhile, or
        # filled by another dispatch, matches nothing
        await s.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id, AgentRun.status == RunStatus.queued, AgentRun.context_at.is_not(None))
            .values(prompt=prompt, context_at=None)
        )
        await s.commit()


async def _clear(run_id: uuid.UUID) -> None:
    async with SessionLocal() as s:
        await s.execute(
            update(AgentRun).where(AgentRun.id == run_id, AgentRun.context_at.is_not(None)).values(context_at=None)
        )
        await s.commit()


async def fill_pending(owner_id: uuid.UUID) -> None:
    """Add the late sections to each queued run of the owner's agents that waits for them, oldest first. Never
    raises: a run whose fill fails has its mark cleared and goes without them, as optional context must never
    hold a run back."""
    try:
        async with SessionLocal() as s:
            run_ids = list((await s.execute(
                select(AgentRun.id)
                .join(Agent, Agent.id == AgentRun.agent_id)
                .where(Agent.owner_id == owner_id, AgentRun.status == RunStatus.queued,
                       AgentRun.context_at.is_not(None))
                .order_by(AgentRun.created_at, AgentRun.id)
            )).scalars())
    except Exception:
        log.exception("late context: listing the queued runs of owner %s failed", owner_id)
        return
    for run_id in run_ids:
        try:
            await _fill(run_id)
        except Exception:
            log.exception("late context: filling run %s failed; it goes without its sections", run_id)
            try:
                await _clear(run_id)
            except Exception:
                log.exception("late context: clearing the mark of run %s failed", run_id)
```
`wf_context.MAX_PROMPT_CHARS` and `wf_context.late_sections` are looked up through the module at call time, so tests can monkeypatch them on `app.workflow.context`.

### B. Helpers at the top of `backend/tests/agent_runs/test_late_context.py` (step 2)
```python
"""The Knowledge Base and Memory sections are added after the commit, before the run is sent (MC-215)."""

import json
import logging
import uuid

from sqlalchemy import update

from app.agent_runs import late_context
from app.agent_runs.models import AgentRun
from app.core.db import SessionLocal
from app.workflow import context
from tests.agent_runs.test_dispatch import _offline_runs

PROMPT = "BASE\n\n## Answer\nyes"
KB, MEM = "## Knowledge Base\nkb", "## Memory\nmem"


async def _kb(db, task, role):
    return KB


async def _mem(db, task, role):
    return MEM


async def _marked(client, db, prompt=PROMPT, at=4, **fields):
    """A queued plan run whose prompt waits for its late sections at `at`."""
    me, agent, runs = await _offline_runs(client, db)
    run_id = uuid.UUID(runs[0]["id"])
    await db.execute(update(AgentRun).where(AgentRun.id == run_id).values(
        workflow_role="plan", stage="plan", prompt=prompt, context_at=at, **fields))
    await db.commit()
    return me, agent, run_id


async def _run(run_id) -> AgentRun:
    async with SessionLocal() as s:
        return await s.get(AgentRun, run_id)
```

### C. `backend/tests/workflow/test_prompt_locks.py` (step 4)
```python
"""Ending a run or approving a document never holds the task, workflow or run lock while the Knowledge Base
and Memory sections wait on the embeddings provider, and a comment to the agent is not held up (MC-215)."""

import asyncio

from sqlalchemy import select, text

from app.agent_runs.models import AgentRun
from app.agent_runs.service import dispatch_pending
from app.ai import client as ai
from app.core.db import SessionLocal
from app.kb import access
from app.tasks.models import Task
from app.workflow import context, engine
from app.workflow.models import TaskWorkflow
from tests.factories import DEFAULT_PASSWORD
from tests.workflow.test_documents import _design_waiting, _submit
from tests.workflow.test_engine import _finish, _runs, _started, _wf


async def _login(client, user):
    r = await client.post("/api/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD})
    assert r.status_code == 200, r.text


def _probe_embeds(monkeypatch, client, task_id, key) -> list[str]:
    """While each embedding call waits, another transaction locks the task, its workflow and its runs (giving up
    after 200 ms), and a comment to the agent goes through the API. Each probe adds "free" or what went wrong."""
    real, seen, busy = ai.embed, [], []

    async def embed(db, texts, **kw):
        if not busy:  # the comment's own request must not probe again
            busy.append(True)
            try:
                async with SessionLocal() as other:
                    await other.execute(text("SET LOCAL lock_timeout = '200ms'"))
                    await other.execute(select(Task.id).where(Task.id == task_id).with_for_update(key_share=True))
                    await other.execute(
                        select(TaskWorkflow.task_id).where(TaskWorkflow.task_id == task_id).with_for_update())
                    await other.execute(select(AgentRun.id).where(AgentRun.task_id == task_id).with_for_update())
                    await other.rollback()
                r = await asyncio.wait_for(client.post(
                    f"/api/tasks/{key}/comments", json={"body_md": "Log retries", "to_agent": True}), 2)
                seen.append("free" if r.status_code == 201 else f"comment {r.status_code}: {r.text}")
            except Exception as exc:  # noqa: BLE001 - the providers swallow errors, so the probe keeps them
                seen.append(repr(exc))
            finally:
                busy.clear()
        return await real(db, texts, **kw)

    monkeypatch.setattr(ai, "embed", embed)
    return seen


async def test_ending_a_run_embeds_without_holding_locks(db, tc_factory, client, monkeypatch):
    tc = tc_factory(lifespan=True)  # registers the Knowledge Base and Memory providers
    await access.ensure_spaces(db)
    await db.commit()
    b, run = await _started(db, tc)
    await _login(client, b.manager)
    seen = _probe_embeds(monkeypatch, client, b.task_id, b.key)
    await _finish(b.manager.id, run, "failed")  # the retry is queued under the run's ending locks
    assert seen and set(seen) == {"free"}, seen
    retry = (await _runs(b.task_id))[-1]
    assert retry.id != run.id and retry.context_at is None


async def test_approving_a_design_embeds_without_holding_locks(db, tc_factory, client, monkeypatch):
    tc = tc_factory(lifespan=True)
    await access.ensure_spaces(db)
    await db.commit()
    b, _ = await _design_waiting(db, tc)
    await _login(client, b.manager)
    seen = _probe_embeds(monkeypatch, client, b.task_id, b.key)
    r = await client.post(f"/api/tasks/{b.key}/documents/design/1/decision", json={"approve": True})
    assert r.status_code == 200, r.text
    assert seen and set(seen) == {"free"}, seen
    plan_run = (await _runs(b.task_id))[-1]
    assert plan_run.workflow_role == "plan" and plan_run.context_at is None


async def _plan_ready(db, tc):
    """A design waiting for approval: the next enqueue may be called directly."""
    b, run = await _started(db, tc)
    await _submit(b, run)
    await _finish(b.manager.id, run, "completed")
    return b


async def test_enqueue_marks_the_place_and_calls_no_late_provider(db, tc_factory, monkeypatch):
    tc = tc_factory(lifespan=True)
    b = await _plan_ready(db, tc)
    calls = []

    async def spy(db_, task_, role_):
        calls.append(role_)
        return "## Knowledge Base\nspy"

    monkeypatch.setattr(context, "late_providers", [spy])
    async with SessionLocal() as s:
        wf = await engine.lock_workflow(s, b.task_id)
        task = await s.get(Task, b.task_id)
        await engine.set_stage(s, wf, task, "plan")
        run = await engine.enqueue(s, wf, task, "plan", requested_by=b.manager.id,
                                   resume_kind="nudge", payload="Keep going")
        assert calls == []
        assert run.prompt[run.context_at:].startswith("\n\n## Reminder\n")
        await s.commit()  # committed, never dispatched: as after a crash
    assert (await _runs(b.task_id))[-1].context_at == run.context_at
    async with SessionLocal() as s:  # the next dispatch for the owner fills it
        await dispatch_pending(s, b.manager.id)
        await s.commit()
    filled = (await _runs(b.task_id))[-1]
    assert calls == ["plan"] and filled.context_at is None
    assert "## Knowledge Base\nspy\n\n## Reminder\n" in filled.prompt
```
If `_finish` "completed" leaves the workflow in a state where `set_stage(..., "plan")` is refused, use `_design_waiting(db, tc)` from `tests/workflow/test_documents.py` instead of `_plan_ready`. The flow is the same as `test_brainstorm_design_and_plan_outputs` in `tests/workflow/test_engine.py`, which does exactly this.

## Steps

### 1. Add the `agent_runs.context_at` column
Model: in `backend/app/agent_runs/models.py`, after `resume_prompt`, add:
```python
    # workflow runs: where in `prompt` the Knowledge Base and Memory sections go, once added after the commit
    # (app/agent_runs/late_context.py); None: the prompt is complete
    context_at: Mapped[int | None]
```
Test first: `backend/tests/agent_runs/test_context_at_migration.py`, following `backend/tests/workflow/test_question_forms_migration.py`. It has `_load_migration()` (glob `*_agent_run_context_at.py`) and two tests:
- `test_the_migration_follows_the_previous_head`: `down_revision == "<head before this step>"`. Find the head with `megoocolab-runner services run migrate -- uv run alembic heads`; today it is `d7b824108d6d`.
- `test_context_at_is_a_nullable_integer(db)`: from `information_schema.columns`, `(is_nullable, data_type) == ("YES", "integer")` for `agent_runs.context_at`.

Run `megoocolab-runner services run test -- uv run pytest tests/agent_runs/test_context_at_migration.py -q`. It fails: no migration file.

Generate: `megoocolab-runner services run migrate -- bash scripts/makemigration.sh "agent run context at"`. Check that the file only has `op.add_column('agent_runs', sa.Column('context_at', sa.Integer(), nullable=True))` and its `drop_column` in downgrade. No backfill.

Check down and up: `megoocolab-runner services run migrate -- bash -c "uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head"`. `uv run alembic heads` shows a single head.

Run the new test plus `tests/core/test_migrations.py`: both pass. Commit: `feat(agent-runs): a run can mark where its late prompt sections go (MC-215)`.

### 2. `late_sections` and `fill_pending`, not wired in yet
`backend/app/workflow/context.py`: below `resume_providers`, add:
```python
# providers that may call an AI provider (the Knowledge Base and Memory): they never run under row locks. Their
# sections are added after the commit that queued the run (app/agent_runs/late_context.py), so they must only read
late_providers: list[ContextProvider] = []
```
and, after `resume_extra`:
```python
async def late_sections(db: AsyncSession, task: Task, role: RunRole) -> list[str]:
    """The late providers' sections, in order; a failing provider is logged and skipped."""
    return [s for p in late_providers if (s := await _provided(db, task, role, p))]
```
Create `backend/app/agent_runs/late_context.py` exactly as **Shared code A**.

Test first: `backend/tests/agent_runs/test_late_context.py` with the helpers from **Shared code B**, and these tests (each monkeypatches `context.late_providers`):
- `test_sections_land_at_the_mark_before_the_resume_note`: `[_kb, _mem]`. `await late_context.fill_pending(me.id)`. The prompt is `"BASE\n\n" + KB + "\n\n" + MEM + "\n\n## Answer\nyes"`, and `context_at is None`.
- `test_sections_that_do_not_fit_are_left_out_last_first`: set `context.MAX_PROMPT_CHARS = len(PROMPT) + len(KB) + 2`. Only KB is added. In a second run with `MAX_PROMPT_CHARS = len(PROMPT) + 3` and providers `[_kb, _tiny]` (a 1-character section), neither is added, although `_tiny` would fit. The mark is cleared both times.
- `test_a_failing_provider_is_skipped`: `[boom, _mem]`, where boom raises RuntimeError. Only MEM is added, and the mark is cleared.
- `test_a_failing_fill_clears_the_mark`: monkeypatch `context.late_sections` to raise RuntimeError. The prompt is unchanged, `context_at is None`, and caplog (ERROR) contains `filling run`.
- `test_a_run_cancelled_during_the_fill_is_not_changed`: a provider that, in its own `SessionLocal`, updates the run to `status="cancelled"` and commits, then returns KB. After the fill, the prompt is still `PROMPT` and `context_at == 4`.
- `test_an_unmarked_or_other_owners_run_is_left_alone`: a run with `context_at=None` keeps its prompt, and `fill_pending(uuid.uuid4())` changes nothing on a marked run.

Before the module exists, the run fails at import. Write the tests, run them, implement, then run `megoocolab-runner services run test -- uv run pytest tests/agent_runs/test_late_context.py tests/workflow/test_context.py -q`: they pass. Lint. Commit: `feat(agent-runs): fill_pending adds a queued run's late prompt sections outside any row lock (MC-215)`.

### 3. `dispatch_pending` fills first, and `_claim_next` skips marked runs
`backend/app/agent_runs/service.py`:
- In `dispatch_pending`, first:
  ```python
  from app.agent_runs.late_context import fill_pending  # local: late_context imports the workflow modules, which import this one

  await fill_pending(owner_id)  # with no row lock held, also when no runner is connected
  ```
  Add to the docstring: "The owner's queued runs first get their Knowledge Base and Memory sections (late_context), with no row lock held."
- In `_claim_next`'s queued-run `select(...).where(...)`, add `AgentRun.context_at.is_(None)` with the comment `# a run waiting for its late sections goes once they are in (late_context)`.

Test first: append to `backend/tests/agent_runs/test_late_context.py`. Import `_claim_next` and `dispatch_pending` from `app.agent_runs.service`, `registry` from `app.runner.registry`, and `_FakeSocket` and `_fake_conn` from `tests.agent_runs.test_dispatch`.
- `test_claim_next_skips_a_marked_run`: `_marked`, then `conn = await _fake_conn(me, agent, _FakeSocket())`. In a `SessionLocal()`, `_claim_next(s, uuid.UUID(agent["id"]), me.id, conn.token_id)` is None. After an update sets `context_at=None`, it returns the run. `registry._conns.pop(me.id, None)` in `finally`.
- `test_dispatch_fills_then_sends`: `[_kb, _mem]`, `_marked`, `_fake_conn` with a `_FakeSocket` `sock`, then `dispatch_pending` in its own session and commit. The `run_start` message in `sock.sent` (json) has a `prompt` that starts with `"BASE\n\n" + KB + "\n\n" + MEM + "\n\n## Answer\nyes"`. The DB run is `running` with `context_at is None`.
- `test_dispatch_without_a_runner_still_fills`: no connection. After `dispatch_pending`, the run is queued, its prompt holds KB, and `context_at is None`.

Run the file: the new tests fail (the claim returns the run; the prompt has no sections). Implement, then run `megoocolab-runner services run test -- uv run pytest tests/agent_runs tests/runner -q -n auto`: pass. Lint. Commit: `feat(agent-runs): a run is sent only after its late prompt sections are in (MC-215)`.

### 4. Move the Knowledge Base and Memory providers out of the locked path
Test first:
- Create `backend/tests/workflow/test_prompt_locks.py` as **Shared code C**.
- `tests/kb/test_context.py::test_context_in_built_prompt`: `late_providers.count(kb_context.kb_context) == 1`, it is not in `context_providers`, `"## Knowledge Base" not in prompt`, and `"## Knowledge Base"` is in `"\n\n".join(await context.late_sections(db, task, RunRole.brainstorm))`.
- `tests/memory/test_context.py::test_provider_registered_after_kb`: the same checks on `context.late_providers`.
- `tests/kb/test_review_fixes.py`: `_restore_providers` also saves and restores `context.late_providers`. `test_kb_section_is_trimmed_before_the_thread` is renamed `test_kb_section_is_left_out_before_the_description_is_cut`. After `build_prompt`, run `prompt = late_context.insert_sections(prompt, len(prompt), await context.late_sections(db, task, RunRole.brainstorm))` with the same patched `MAX_PROMPT_CHARS`. Same asserts.

Run `megoocolab-runner services run test -- uv run pytest tests/workflow/test_prompt_locks.py tests/kb/test_context.py tests/kb/test_review_fixes.py tests/memory/test_context.py -q`. The probes record lock timeouts or a comment `TimeoutError`, `context_at` is None after enqueue, and the registration tests fail.

Implement:
- `kb/context.py` and `memory/context.py` `register()`: `if X not in context.late_providers: context.late_providers.append(X)`.
- `engine.enqueue`: right after `build_prompt(...)`, add `context_at = len(prompt)  # the late sections go here, before any resume note (late_context)`, and pass `context_at=context_at` to `AgentRun(...)`.
- Engine docstring, after the lock list: "Nothing that calls an AI provider runs under these locks: a queued run's Knowledge Base and Memory sections are added after the commit, in dispatch_pending (app/agent_runs/late_context.py), which takes the run row alone, for one UPDATE."
- `context.py`: the `context_providers` comment says they only read the DB (slow AI calls go in `late_providers`). The trim comment becomes `# optional context (other projects, earlier rounds) goes before anything about the task itself`.

Run the same command: it passes. Regression: `megoocolab-runner services run test -- uv run pytest tests/workflow tests/mcp tests/agent_runs tests/runner tests/kb tests/memory tests/a2a tests/chats tests/triggers -q -n auto`. Lint. Commit: `fix(workflow): the Knowledge Base and Memory sections are built after the commit, never under the task, workflow or run locks (MC-215)`.

## Final verification
From `backend/`:
1. `megoocolab-runner services run test -- uv run pytest tests/workflow/test_prompt_locks.py tests/agent_runs/test_late_context.py tests/agent_runs/test_context_at_migration.py tests/core/test_migrations.py -q`
2. `megoocolab-runner services run test -- uv run pytest tests/workflow tests/mcp tests/agent_runs tests/runner tests/kb tests/memory tests/a2a tests/chats tests/triggers -q -n auto`
3. `megoocolab-runner services run migrate -- bash -c "uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head && uv run alembic heads"`: one head.
4. `uvx ruff check --select E9,F app tests`
