"""Waiting on another project's answer: a run that ends needing an answer waits quietly, and only then."""

import uuid
from types import SimpleNamespace

from sqlalchemy import func, select

from app.a2a.models import Question
from app.chats import service as chats
from app.chats.models import Chat, ChatMode
from app.core.db import SessionLocal
from app.notifications.models import Notification
from app.projects.models import Project
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


# ---- picking up again ------------------------------------------------------------------------------------------

import asyncio  # noqa: E402

from sqlalchemy import update  # noqa: E402

from app.a2a import context as a2a_ctx  # noqa: E402
from app.a2a import routing, service, waits  # noqa: E402
from app.tasks.models import Comment, Delivery  # noqa: E402
from app.workflow.models import RunRole  # noqa: E402
from tests.runner.test_runner_ws import _login  # noqa: E402
from tests.workflow.test_engine import _member  # noqa: E402


async def _answer(qid, text="Signed with HMAC in app/sign.py") -> None:
    async with SessionLocal() as s:
        await s.execute(update(Question).where(Question.id == qid).values(
            status="answered", answer_md=text, citations=[{"path": "app/sign.py", "start_line": 1, "end_line": 3}]))
        await s.commit()


async def _waiting_on(db, tc, n=1):
    """A started workflow whose brainstorm run asked n questions it needs and ended: waiting on them."""
    b, run = await _started(db, tc)
    qids = [await _wait_q(b.task_id) for _ in range(n)]
    await _finish(b.manager.id, run, "completed", session_id="sess-1")
    assert (await _wf(b.task_id)).needs == "project_answer"
    return b, qids


async def _q(qid) -> Question:
    async with SessionLocal() as s:
        return await s.get(Question, qid)


async def test_answered_before_run_end_resumes_at_once(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    qid = await _wait_q(b.task_id)
    await _answer(qid)
    await _finish(b.manager.id, run, "completed", session_id="sess-1")
    runs = await _runs(b.task_id)
    assert len(runs) == 2 and runs[-1].workflow_role == "brainstorm"
    assert "Answers from other projects arrived." in runs[-1].resume_prompt
    assert "Signed with HMAC" in runs[-1].resume_prompt
    assert (await _wf(b.task_id)).nudged is False
    assert (await _q(qid)).delivered_at is not None


async def test_last_answer_resumes_same_session_with_answers(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, [qid] = await _waiting_on(db, tc)
    assert await waits.resume_settled() == 0
    await _answer(qid)
    assert await waits.resume_settled() == 1
    new = (await _runs(b.task_id))[-1]
    assert (new.workflow_role, new.resume_session_ref) == ("brainstorm", "sess-1")
    assert new.resume_prompt.startswith("Answers from other projects arrived.")
    assert "Signed with HMAC" in new.resume_prompt and "app/sign.py:1-3" in new.resume_prompt
    assert new.resume_prompt.count("Signed with HMAC") == 1  # not again in the tail
    assert (await _wf(b.task_id)).status == "running"


async def test_two_questions_resume_once_after_second_answer(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, [q1, q2] = await _waiting_on(db, tc, n=2)
    await _answer(q1)
    assert await waits.resume_settled() == 0
    await _answer(q2, "Header X-Signature")
    assert await waits.resume_settled() == 1
    runs = await _runs(b.task_id)
    assert len(runs) == 2
    assert "Signed with HMAC" in runs[-1].resume_prompt and "X-Signature" in runs[-1].resume_prompt


async def test_two_settled_passes_resume_once(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, [qid] = await _waiting_on(db, tc)
    await _answer(qid)
    assert sum(await asyncio.gather(waits.resume_settled(), waits.resume_settled())) == 1
    assert len(await _runs(b.task_id)) == 2


async def test_go_on_without_it_resumes_with_unanswered_line_and_late_answer_never_resumes(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, [qid] = await _waiting_on(db, tc)
    r = tc.post(f"/api/tasks/{b.key}/project-waits/go-on")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "running"
    new = (await _runs(b.task_id))[-1]
    q = await _q(qid)
    ref = service.ref_of(await db.get(Project, q.target_project_id), q)
    assert f"{ref} wasn't answered. Carry on with what you have" in new.resume_prompt
    q = await _q(qid)
    assert (q.wait, q.status) == (False, "queued")  # still open, as an ordinary question
    await _finish(b.manager.id, new, "completed", session_id="sess-1")  # nudged as usual: nothing holds it
    await _answer(qid, "Late answer")
    assert await waits.resume_settled() == 0
    count = len(await _runs(b.task_id))
    async with SessionLocal() as s:
        section = await a2a_ctx.a2a_context(s, await s.get(Task, b.task_id), RunRole.brainstorm)
    assert "Late answer" in section
    assert len(await _runs(b.task_id)) == count


async def test_withdraw_last_wait_resumes(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, [qid] = await _waiting_on(db, tc)
    r = tc.post(f"/api/questions/{qid}/withdraw")
    assert r.status_code == 200, r.text
    assert await waits.resume_settled() == 1
    assert "wasn't answered" in (await _runs(b.task_id))[-1].resume_prompt


async def test_task_actor_may_withdraw_agent_question(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, [qid] = await _waiting_on(db, tc)
    member = await _member(db, tc)
    _login(tc, member)
    assert tc.get(f"/api/questions/{qid}").json()["can_withdraw"] is False
    assert tc.post(f"/api/questions/{qid}/withdraw").status_code == 403
    _login(tc, b.manager)
    assert tc.get(f"/api/questions/{qid}").json()["can_withdraw"] is True
    assert tc.post(f"/api/questions/{qid}/withdraw").status_code == 200


async def test_freestyle_chat_resumes_as_a_turn_with_waiting_message(client, db):
    w, task_id, run = await _freestyle(client, db)
    qid = await _wait_q(task_id)
    await _waiting_comment(task_id, w, after=run)
    await _end(run.id)
    assert (await _wf(task_id)).needs == "project_answer"
    await _answer(qid)
    assert await waits.resume_settled() == 1
    new = (await _runs(task_id))[-1]
    assert new.workflow_role == "freestyle" and "Signed with HMAC" in (new.resume_prompt or new.prompt)
    async with SessionLocal() as s:  # the message waits for this turn's start (take_waiting at dispatch)
        delivery = await s.scalar(select(Comment.delivery).where(Comment.task_id == task_id))
    assert delivery == Delivery.waiting


async def test_go_on_refused_when_not_waiting(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _run = await _started(db, tc)
    r = tc.post(f"/api/tasks/{b.key}/project-waits/go-on")
    assert (r.status_code, r.json()["detail"]) == (409, "not_waiting")


async def test_on_answered_wakes_routing_after_commit(db, tc_factory, monkeypatch):
    tc = tc_factory(lifespan=True)
    b, [qid] = await _waiting_on(db, tc)
    calls = []
    monkeypatch.setattr(routing, "wake", lambda: calls.append(1))
    async with SessionLocal() as s:
        q = await s.get(Question, qid)
        q.status, q.answer_md, q.answered_by_user_id = "answered", "x", b.manager.id
        await service.on_answered(s, q)
        assert calls == []  # not before the answer is committed
        await s.commit()
    assert calls == [1]


# ---- telling the person ---------------------------------------------------------------------------------------

from datetime import UTC, datetime, timedelta  # noqa: E402

from app.org.models import ORG_SETTINGS_ID, OrgSettings  # noqa: E402


async def _told(task_id) -> list[Notification]:
    async with SessionLocal() as s:
        rows = await s.execute(select(Notification).where(Notification.task_id == task_id,
                                                          Notification.kind == "question_waiting"))
        return list(rows.scalars())


async def _org_minutes(minutes: int) -> None:
    async with SessionLocal() as s:
        org = await s.get(OrgSettings, ORG_SETTINGS_ID)
        if org is None:
            s.add(OrgSettings(id=ORG_SETTINGS_ID, name="Acme", project_answer_notify_minutes=minutes))
        else:
            org.project_answer_notify_minutes = minutes
        await s.commit()


async def test_needs_human_tells_asker_once(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, [qid] = await _waiting_on(db, tc)
    for _ in range(2):
        async with SessionLocal() as s:
            await waits.notify_asker(s, await s.get(Question, qid), "human")
            await s.commit()
    [n] = await _told(b.task_id)
    q = await _q(qid)
    project = await db.get(Project, q.target_project_id)
    ref = service.ref_of(project, q)
    assert n.title == f"{ref} is waiting for a person at {project.key} to answer."
    assert n.user_id == b.manager.id and n.body == q.title


async def test_slow_answer_tells_asker_after_setting_minutes_once(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, [qid] = await _waiting_on(db, tc)
    await _org_minutes(5)
    assert await waits.notify_slow() == 0  # not yet
    async with SessionLocal() as s:
        await s.execute(update(Question).where(Question.id == qid)
                        .values(created_at=datetime.now(UTC) - timedelta(minutes=6)))
        await s.commit()
    assert await waits.notify_slow() == 1
    assert await waits.notify_slow() == 0
    [n] = await _told(b.task_id)
    q = await _q(qid)
    project = await db.get(Project, q.target_project_id)
    assert n.title == f"{project.key} hasn't answered {service.ref_of(project, q)} yet."


async def test_question_without_wait_tells_asker_nothing(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _run = await _started(db, tc)
    qid = await _wait_q(b.task_id, wait=False)
    await _org_minutes(5)
    async with SessionLocal() as s:
        await s.execute(update(Question).where(Question.id == qid)
                        .values(created_at=datetime.now(UTC) - timedelta(minutes=60)))
        await s.commit()
        await waits.notify_asker(s, await s.get(Question, qid), "human")
        await s.commit()
    assert await waits.notify_slow() == 0
    assert await _told(b.task_id) == []


async def test_routing_giving_up_tells_asker(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, [qid] = await _waiting_on(db, tc)
    async with SessionLocal() as s:  # every agent bound to the target has tried: the question goes to a person
        from app.agents.models import AgentBinding

        target = (await s.get(Question, qid)).target_project_id
        bound = (await s.execute(select(AgentBinding.agent_id).where(AgentBinding.project_id == target))).scalars()
        await s.execute(update(Question).where(Question.id == qid)
                        .values(tried_agent_ids=[str(a) for a in bound] + [str(uuid.uuid4())]))
        await s.commit()
    async with SessionLocal() as s:
        await routing.route_question(s, qid)
        await s.commit()
    assert (await _q(qid)).status == "needs_human"
    assert [n.title.endswith("to answer.") for n in await _told(b.task_id)] == [True]


# ---- what the screens are told --------------------------------------------------------------------------------


async def test_workflow_out_lists_project_waits_with_viewer_rights(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, [qid] = await _waiting_on(db, tc)
    body = tc.get(f"/api/tasks/{b.key}/workflow").json()
    assert body["needs"] == "project_answer"
    [w] = body["project_waits"]
    q = await _q(qid)
    project = await db.get(Project, q.target_project_id)
    assert w == {"question_id": str(qid), "ref": service.ref_of(project, q), "project_key": project.key,
                 "title": q.title, "status": "queued", "can_answer": True, "can_withdraw": True}
    member = await _member(db, tc)
    _login(tc, member)
    [w] = tc.get(f"/api/tasks/{b.key}/workflow").json()["project_waits"]
    assert w["can_withdraw"] is False


async def test_chat_out_state_waiting_answer_and_refs(client, db):
    from app.workflow import engine
    from tests.chats.helpers import start, world

    await world(client, db)
    chat = await start(client)
    task_id = await db.scalar(select(Task.id).where(Task.chat_id == uuid.UUID(chat["id"])))
    qid = await _wait_q(task_id)
    async with SessionLocal() as s:
        wf = await engine.lock_workflow(s, task_id)
        await engine.wait_for(s, wf, "project_answer", notify=False)
        await s.commit()
    body = (await client.get(f"/api/chats/{chat['id']}")).json()
    q = await _q(qid)
    project = await db.get(Project, q.target_project_id)
    assert body["state"] == "waiting_answer" and body["waiting_on"] == [service.ref_of(project, q)]
    assert body["intent"] == "tell"
