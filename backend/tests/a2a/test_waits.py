"""Waiting on another project's answer: a run that ends needing an answer waits quietly, and only then."""

import uuid
from types import SimpleNamespace

from sqlalchemy import func, select

from app.a2a.models import Question
from app.chats import service as chats
from app.chats.models import Chat, ChatMode
from app.core.db import SessionLocal
from app.notifications.models import Notification
from app.tasks.models import Task
from tests.workflow.test_build import _building, _complete
from tests.workflow.test_engine import _ask, _finish, _runs, _started, _wf
from tests.workflow.test_freestyle_engine import _end, _freestyle, _waiting_comment

_numbers = iter(range(1, 10_000))


async def _wait_q(task_id, *, wait=True, status="queued") -> uuid.UUID:
    """A question the task asked (of its own project, which is enough here), open unless `status` says not."""
    async with SessionLocal() as s:
        task = await s.get(Task, task_id)
        q = Question(target_project_id=task.project_id, number=next(_numbers) + 1000, from_task_id=task_id,
                     title="How is it signed?", body="b", wait=wait, status=status)
        s.add(q)
        await s.commit()
        return q.id


async def _needs_you_count(task_id) -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(func.count()).select_from(Notification).where(
            Notification.task_id == task_id, Notification.kind == "needs_you"))


async def test_brainstorm_ending_with_open_wait_question_waits_quietly(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _wait_q(b.task_id)
    await _finish(b.manager.id, run, "completed", session_id="sess-1")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.nudged) == ("waiting_human", "project_answer", False)
    assert len(await _runs(b.task_id)) == 1  # no nudge
    assert await _needs_you_count(b.task_id) == 0


async def test_freestyle_turn_with_open_wait_waits_and_queues_no_turn(client, db):
    w, task_id, run = await _freestyle(client, db)
    await _wait_q(task_id)
    await _waiting_comment(task_id, w, after=run)
    await _end(run.id)
    wf = await _wf(task_id)
    assert (wf.status, wf.needs) == ("waiting_human", "project_answer")
    assert len(await _runs(task_id)) == 1


async def test_implement_with_wait_question_is_not_step_incomplete(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _building(db, tc)
    await _wait_q(b.task_id)
    await _finish(b.manager.id, run, "completed", session_id="impl-1")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.escalation_reason, wf.nudged) == ("waiting_human", "project_answer", None, False)


async def test_completed_step_with_wait_question_is_not_held(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _building(db, tc)
    await _wait_q(b.task_id)
    await _complete(run)
    await _finish(b.manager.id, run, "completed", session_id="impl-1")
    wf = await _wf(b.task_id)
    assert wf.needs != "project_answer" and wf.status == "running"
    assert (await _runs(b.task_id))[-1].workflow_role == "step_review"


async def test_ask_human_question_takes_precedence(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _wait_q(b.task_id)
    qid = await _ask(b.task_id, run.id)
    await _finish(b.manager.id, run, "completed", session_id="sess-1")
    assert (await _wf(b.task_id)).needs == "question"
    r = tc.post(f"/api/tasks/{b.key}/questions/{qid}/answer", json={"text": "Postgres"})
    assert r.status_code == 200, r.text
    second = (await _runs(b.task_id))[-1]
    await _finish(b.manager.id, second, "completed", session_id="sess-1")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs) == ("waiting_human", "project_answer")


async def test_questions_without_wait_never_hold(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _wait_q(b.task_id, wait=False)
    await _finish(b.manager.id, run, "completed", session_id="sess-1")
    wf = await _wf(b.task_id)
    assert wf.needs is None and wf.nudged is True  # the usual nudge
    assert len(await _runs(b.task_id)) == 2


async def test_failed_run_does_not_hold(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _wait_q(b.task_id)
    await _finish(b.manager.id, run, "failed")
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs, wf.failures) == ("running", None, 1)
    assert len(await _runs(b.task_id)) == 2  # retried as usual


async def test_resumed_paused_workflow_returns_to_project_answer(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _wait_q(b.task_id)
    await _finish(b.manager.id, run, "completed", session_id="sess-1")
    assert tc.post(f"/api/tasks/{b.key}/workflow/pause").status_code == 200
    r = tc.post(f"/api/tasks/{b.key}/workflow/resume")
    assert r.status_code == 200, r.text
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs) == ("waiting_human", "project_answer")
    assert len(await _runs(b.task_id)) == 1


async def test_message_while_waiting_is_tell_and_starts_nothing():
    wf = SimpleNamespace(status="waiting_human", needs="project_answer", escalation_reason=None)
    task = SimpleNamespace(id=uuid.uuid4())

    class _Db:  # intent asks the engine for the active run, and there is none
        async def scalar(self, *a, **k):
            return None

        async def execute(self, *a, **k):
            return SimpleNamespace(scalar_one_or_none=lambda: None, scalars=lambda: SimpleNamespace(first=lambda: None))

    for mode in (ChatMode.workflow, ChatMode.freestyle):
        chat = Chat(title="c", mode=mode, status="open")
        assert await chats.intent(_Db(), chat, task, wf) == "tell", mode
