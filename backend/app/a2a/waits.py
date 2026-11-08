"""Waiting on another project's answer.

An agent asks with `wait=True` when it can't go on without the answer. The wait is decided when one of the task's
runs ends, not when the agent asks, and it belongs to the task: while any of its `wait` questions is open, a run that
ended without its role's own outcome leaves the workflow waiting (`Needs.project_answer`), quietly: nobody is asked.
"""

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.a2a.models import OPEN_STATUSES, Question, QuestionStatus
from app.agent_runs.models import AgentRun
from app.agents.models import Agent
from app.auth.models import User
from app.core.db import SessionLocal
from app.notifications import service as notifications
from app.notifications.models import Kind
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.projects.models import Project
from app.tasks.models import Task
from app.workflow.models import (
    DocStatus,
    Driver,
    Needs,
    RunRole,
    StepReview,
    TaskWorkflow,
    WorkflowDocument,
    WorkflowStatus,
)


log = logging.getLogger(__name__)

# finishing has no next step to wait for; a pull request's review may run on another agent (the project's reviewer),
# whose session the task's own agent could never resume
NEVER_HELD = frozenset({RunRole.finish, RunRole.pr_review})


async def open_waits(db: AsyncSession, task_id) -> list[Question]:
    """The task's questions it can't go on without, still open, oldest first."""
    rows = await db.execute(
        select(Question)
        .where(Question.from_task_id == task_id, Question.wait.is_(True), Question.status.in_(OPEN_STATUSES))
        .order_by(Question.created_at, Question.id)
    )
    return list(rows.scalars())


async def produced_outcome(db: AsyncSession, run: AgentRun) -> bool:
    """Did the run leave its role's own outcome (a question for a person, a document, a review, a step result)?
    Then its role's handler decides what comes next, and any open wait holds the task only at a later run's end."""
    from app.workflow import questions  # local: questions imports the engine, which imports this module lazily

    if run.step_result:
        return True
    if await questions.has_open_question(db, run.id):
        return True
    if await questions.undelivered_answer(db, run.task_id, run.id) is not None:
        return True  # a person answered it while it worked: its handler hands that answer over first
    submitted = await db.scalar(
        select(WorkflowDocument.id)
        .where(WorkflowDocument.submitted_run_id == run.id, WorkflowDocument.status == DocStatus.submitted)
        .limit(1)
    )
    if submitted is not None:
        return True
    return await db.scalar(select(StepReview.id).where(StepReview.run_id == run.id).limit(1)) is not None


async def hold_after_run(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> bool:
    """Called at a run's normal end, before its role's handler. True: the end is handled (the task waits)."""
    from app.workflow import engine  # local: the engine imports this module lazily

    if RunRole(run.workflow_role) in NEVER_HELD or await produced_outcome(db, run):
        return False
    if await open_waits(db, task.id):
        await engine.wait_for(db, wf, Needs.project_answer, notify=False)
        return True
    if await _settled_undelivered(db, task.id):  # answered while the run still worked: it picks up at once
        await settle(db, wf, task, requested_by=await engine.owner_id(db, run))
        return True
    return False


# ---- picking up again ------------------------------------------------------------------------------------------


async def _settled_undelivered(db: AsyncSession, task_id) -> list[Question]:
    rows = await db.execute(
        select(Question)
        .where(Question.from_task_id == task_id, Question.wait.is_(True), Question.delivered_at.is_(None),
               Question.status.in_((QuestionStatus.answered, QuestionStatus.withdrawn)))
        .order_by(Question.created_at, Question.id)
    )
    return list(rows.scalars())


async def _ref(db: AsyncSession, q: Question) -> str:
    project = await db.get(Project, q.target_project_id)
    return f"{project.key}-Q{q.number}"


async def settle(
    db: AsyncSession, wf: TaskWorkflow, task: Task, *, requested_by: uuid.UUID, gave_up: Sequence[Question] = ()
) -> AgentRun | None:
    """The agent picks up again, in the session of the role that was running, with the answers that arrived and a
    line for each question it goes on without. The caller holds the engine's locks (task, then workflow)."""
    from app.workflow import engine  # local: the engine imports this module lazily

    settled = await _settled_undelivered(db, task.id)
    answers = [
        {"ref": await _ref(db, q), "title": q.title, "answer_md": q.answer_md or "", "citations": q.citations or []}
        for q in settled if q.status == QuestionStatus.answered
    ]
    unanswered = [await _ref(db, q) for q in settled if q.status != QuestionStatus.answered]
    unanswered += [await _ref(db, q) for q in gave_up]
    now = datetime.now(UTC)
    for q in settled:
        q.delivered_at = now
    await db.flush()
    last = await engine.latest_run(db, task.id)
    role = RunRole(last.workflow_role)
    return await engine.hand_to_agent(
        db, wf, task, role, step=last.step, resume_kind="project_answers",
        payload={"answers": answers, "unanswered": unanswered}, requested_by=requested_by,
        resume_session_ref=last.session_ref if role in engine.FRESH_ROLES else None,
    )


async def resume_settled() -> int:
    """The loop's pass: every workflow waiting on answers that have all arrived (or been withdrawn) picks up again.
    Each in a session of its own, under the engine's locks (skipped, not waited for, while another holds them),
    the state checked again under them."""
    from app.workflow import engine  # local: the engine imports this module lazily

    async with SessionLocal() as s:
        task_ids = list((await s.execute(
            select(TaskWorkflow.task_id).where(TaskWorkflow.status == WorkflowStatus.waiting_human,
                                               TaskWorkflow.needs == Needs.project_answer,
                                               TaskWorkflow.driver == Driver.runner)
        )).scalars())
    resumed = 0
    for task_id in task_ids:
        try:
            resumed += await _resume_one(task_id)
        except Exception:  # one task that can't pick up again must not hold up the others
            log.exception("resuming task %s after other projects' answers failed", task_id)
    return resumed


async def _resume_one(task_id) -> int:
    from app.workflow import engine  # local: the engine imports this module lazily

    async with SessionLocal() as s:
        # the engine's locks, task then workflow, never waited for: a task busy now is taken by the next pass
        if await s.scalar(select(Task.id).where(Task.id == task_id)
                          .with_for_update(key_share=True, skip_locked=True)) is None:
            return 0
        wf = (await s.execute(
            select(TaskWorkflow).where(TaskWorkflow.task_id == task_id).with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )).scalar_one_or_none()
        task = await s.get(Task, task_id)
        if wf is None or wf.status != WorkflowStatus.waiting_human or wf.needs != Needs.project_answer:
            return 0
        if await open_waits(s, task_id):
            return 0
        last = await engine.latest_run(s, task_id)
        if last is None or last.workflow_role is None:
            return 0  # no run to pick up from
        await settle(s, wf, task, requested_by=await engine.owner_id(s, last))
        await engine.dispatch_queued(s)
        await s.commit()
        return 1


async def go_on_without(db: AsyncSession, user: User, task: Task) -> TaskWorkflow:
    """"Go on without it": the open questions stay open as ordinary ones, and the agent picks up again now."""
    from app.workflow import engine  # local: the engine imports this module lazily

    wf = await engine.lock_task(db, task)
    await engine.require_actor(db, user, task, wf)
    if wf is None or wf.status != WorkflowStatus.waiting_human or wf.needs != Needs.project_answer:
        raise HTTPException(status.HTTP_409_CONFLICT, "not_waiting")
    pending = await open_waits(db, task.id)
    for q in pending:
        q.wait = False
    await db.flush()
    await engine.record_workflow_event(db, task, user.id, "project_answers.gone_on", {"count": len(pending)})
    await settle(db, wf, task, requested_by=user.id, gave_up=pending)
    return wf


_WAKE_KEY = "a2a.wake_after_commit"


def wake_after_commit(db: AsyncSession) -> None:
    """Once this session commits, wake the routing loop: a waiting task may pick up again. Never inside the
    transaction that answered: the engine's lock order (task, workflow, question) forbids resuming there."""
    sync = db.sync_session
    if sync.info.get(_WAKE_KEY):
        return
    sync.info[_WAKE_KEY] = True

    def _after_commit(session) -> None:
        session.info.pop(_WAKE_KEY, None)
        from app.a2a import routing  # local: routing imports the service, which imports this module

        routing.wake()

    event.listen(sync, "after_commit", _after_commit, once=True)


# ---- telling the asking task's people -------------------------------------------------------------------------

DEFAULT_NOTIFY_MINUTES = 30


async def _asking_people(db: AsyncSession, task: Task) -> tuple[list, str]:
    """Who is told the task needs them, and where to: as `engine.wait_for` picks them."""
    project = await db.get(Project, task.project_id)
    wf = await db.get(TaskWorkflow, task.id)
    agent_id = (wf.agent_id if wf else None) or task.assignee_agent_id
    owner = await db.scalar(select(Agent.owner_id).where(Agent.id == agent_id)) if agent_id else None
    key = f"{project.key}-{task.number}"
    if task.in_chat:
        from app.chats.service import chat_people  # local: the chats modules import the engine

        return await chat_people(db, task)
    return [owner, task.assignee_user_id], f"/projects/{project.key}/board?task={key}"


async def notify_asker(db: AsyncSession, q: Question, kind: str) -> None:
    """Tell the asking task's people, once per kind and question it needs: "human" (the question went to a person
    at the other project) or "slow" (no answer after the org's notify minutes)."""
    if not q.wait or q.from_task_id is None:
        return
    column = "asker_human_notified_at" if kind == "human" else "asker_slow_notified_at"
    if getattr(q, column) is not None:
        return
    setattr(q, column, datetime.now(UTC))
    task = await db.get(Task, q.from_task_id)
    if task is None:
        return
    target = await db.get(Project, q.target_project_id)
    ref = f"{target.key}-Q{q.number}"
    title = (f"{ref} is waiting for a person at {target.key} to answer." if kind == "human"
             else f"{target.key} hasn't answered {ref} yet.")
    recipients, link = await _asking_people(db, task)
    await notifications.notify(db, recipients, Kind.question_waiting, title=title, body=q.title, link=link,
                               task_id=task.id, project_id=task.project_id)


async def notify_slow() -> int:
    """The loop's pass: the questions a task waits for that are still open after the org's notify minutes."""
    async with SessionLocal() as s:
        org = await s.get(OrgSettings, ORG_SETTINGS_ID)
        minutes = org.project_answer_notify_minutes if org is not None else DEFAULT_NOTIFY_MINUTES
        rows = await s.execute(
            select(Question)
            .where(Question.wait.is_(True), Question.from_task_id.is_not(None), Question.status.in_(OPEN_STATUSES),
                   Question.asker_slow_notified_at.is_(None),
                   Question.created_at <= datetime.now(UTC) - timedelta(minutes=minutes))
            .with_for_update(skip_locked=True)
        )
        told = 0
        for q in rows.scalars():
            await notify_asker(s, q, "slow")
            told += 1
        await s.commit()
        return told
