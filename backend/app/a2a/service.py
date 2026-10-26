"""Asking a project (A2A-1), suggestions from the KB and memory before routing (A2A-6), withdrawing."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.a2a.access import (
    OPEN_QUESTION_CAP,
    can_answer_question,
    can_read_question,
    open_question_count,
)
from app.a2a.models import OPEN_STATUSES, Question, QuestionStatus
from app.a2a.schemas import (
    Citation,
    Draft,
    QuestionOut,
    Ref,
    Suggestion,
    Target,
    TaskRef,
    Who,
)
from app.agent_runs.models import ACTIVE_STATUSES, AgentRun, RunStatus
from app.agents.models import Agent
from app.audit import service as audit
from app.auth.models import Role, User
from app.core.events import Event, publish
from app.core.text import strip_nul
from app.jobs import queue
from app.kb import access as kb_access
from app.kb import search as kb_search
from app.memory.search import search_conclusions
from app.projects.models import Project
from app.tasks.models import Task
from app.tasks.service import get_task_for

TITLE_MAX = 200
SUGGESTIONS = 5
KB_SUGGESTIONS = 3


async def project_by_key(db: AsyncSession, key: str) -> Project:
    project = (await db.execute(select(Project).where(Project.key == key.strip().upper()))).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project_not_found")
    return project


def ref_of(project: Project, q: Question) -> str:
    return f"{project.key}-Q{q.number}"


async def notify(db: AsyncSession, q: Question) -> None:
    """Live views: the target project's members, and the asker (who may not be one)."""
    await publish(db, Event(type="question.updated", project_id=q.target_project_id))
    if q.asked_by_user_id:
        await publish(db, Event(type="question.updated", user_id=q.asked_by_user_id))
    if q.from_task_id:
        project_id = await db.scalar(select(Task.project_id).where(Task.id == q.from_task_id))
        await publish(db, Event(type="task.updated", project_id=project_id, task_id=q.from_task_id))


async def suggest(db: AsyncSession, user: User, project_id: uuid.UUID, text: str) -> list[Suggestion]:
    """Existing answers the asker can read: the target project's KB (and the org's), then memory."""
    out: list[Suggestion] = []
    spaces = {(await kb_access.space_for_project(db, project_id)).id, (await kb_access.org_space(db)).id}
    found = await kb_search.search(db, user, text, space_ids=spaces, limit=KB_SUGGESTIONS, match_any=True)
    for hit in found["results"]:
        out.append(Suggestion(kind="kb", id=hit["document_id"], title=hit["title"], snippet=hit["snippet"][:300],
                              link=f"/kb/doc/{hit['document_id']}"))
    for c in await search_conclusions(db, user, text, project_id=project_id, limit=SUGGESTIONS - len(out)):
        out.append(Suggestion(kind="memory", id=c.id, title=c.text[:200], snippet=(c.source_label or "")[:300],
                              link=f"/memory/entity/{c.entity_id}"))
    return out[:SUGGESTIONS]


async def ask(
    db: AsyncSession,
    user: User,
    *,
    project_key: str,
    body: str,
    title: str | None = None,
    context: str = "",
    task_key: str | None = None,
    agent_id: uuid.UUID | None = None,
) -> tuple[Question, list[Suggestion]]:
    if user.role == Role.viewer:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    body = strip_nul(body).strip()
    context = strip_nul(context or "").strip()
    if not body:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_question")
    title = strip_nul(title or "").strip() or body.splitlines()[0].strip()
    title = title[:TITLE_MAX]
    task = None
    if task_key:
        task, _ = await get_task_for(db, user, task_key, write=True)
    project = await project_by_key(db, project_key)
    if await open_question_count(db, user) >= OPEN_QUESTION_CAP:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_open_questions")
    locked = (await db.execute(select(Project).where(Project.id == project.id).with_for_update())).scalar_one()
    number = locked.next_question_number
    locked.next_question_number = number + 1
    q = Question(
        target_project_id=project.id, number=number, from_task_id=task.id if task else None,
        asked_by_user_id=user.id, asked_by_agent_id=agent_id, title=title, body=body, context=context,
    )
    db.add(q)
    await db.flush()
    if task is not None:
        from app.tasks.service import (
            record_event,  # local: tasks import nothing from a2a
        )

        await record_event(db, task, user.id, "question_asked",
                           {"question_id": str(q.id), "target_key": project.key, "number": number})
    await audit.record(db, "a2a.question.asked", actor_id=user.id, target_type="question", target_id=q.id,
                       data={"target": project.key, "number": number, "agent_id": str(agent_id) if agent_id else None})
    await notify(db, q)
    await queue.enqueue(db, "a2a.route", {}, dedupe_key="a2a.route")
    return q, await suggest(db, user, project.id, f"{title}\n{body}")


async def cancel_question_runs(db: AsyncSession, q: Question, actor_id: uuid.UUID | None) -> None:
    """Stops an answering run that is no longer needed (answered by someone else, or withdrawn)."""
    from app.agent_runs.service import _lock_run, _transition
    from app.runner.protocol import RunCancel
    from app.runner.registry import RunnerClosed, registry

    runs = (
        await db.execute(
            select(AgentRun.id).where(AgentRun.question_id == q.id, AgentRun.status.in_(ACTIVE_STATUSES))
        )
    ).scalars().all()
    for run_id in runs:
        run = await _lock_run(db, run_id)
        if run is None or run.status not in ACTIVE_STATUSES:
            continue
        owner_id = await db.scalar(select(Agent.owner_id).where(Agent.id == run.agent_id))
        run.cancelled_by = actor_id
        if run.status == RunStatus.running:
            conn = registry.conn_for_user(owner_id)
            if conn is not None and run.id in conn.run_ids:
                try:
                    await conn.send(RunCancel(run_id=run.id))
                    continue
                except RunnerClosed:
                    pass
        await _transition(db, run, RunStatus.cancelled, "agent_run_cancelled", owner_id=owner_id, actor_id=actor_id)


async def lock_question(db: AsyncSession, question_id: uuid.UUID) -> Question:
    q = (
        await db.execute(
            select(Question).where(Question.id == question_id).with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if q is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "question_not_found")
    return q


async def withdraw(db: AsyncSession, user: User, q: Question) -> Question:
    q = await lock_question(db, q.id)
    if q.asked_by_user_id != user.id and user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    if q.status not in OPEN_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "not_open")
    q.status = QuestionStatus.withdrawn
    await cancel_question_runs(db, q, user.id)
    await audit.record(db, "a2a.question.withdrawn", actor_id=user.id, target_type="question", target_id=q.id)
    await notify(db, q)
    await db.flush()
    return q


async def get_question_for(db: AsyncSession, user: User, question_id: uuid.UUID) -> Question:
    q = await db.get(Question, question_id)
    if q is None or not await can_read_question(db, user, q):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "question_not_found")
    return q


async def _who(db: AsyncSession, user_id, agent_id) -> Who:
    user = await db.get(User, user_id) if user_id else None
    agent = await db.get(Agent, agent_id) if agent_id else None
    return Who(user=Ref(id=user.id, name=user.name) if user else None,
               agent=Ref(id=agent.id, name=agent.name) if agent else None)


async def can_approve(db: AsyncSession, user: User, q: Question) -> bool:
    if q.status != QuestionStatus.draft:
        return False
    if user.role == Role.admin:
        return True
    owner = await db.scalar(select(Agent.owner_id).where(Agent.id == q.draft_agent_id)) if q.draft_agent_id else None
    return owner == user.id


async def question_out(db: AsyncSession, user: User, q: Question) -> QuestionOut:
    project = await db.get(Project, q.target_project_id)
    task = await db.get(Task, q.from_task_id) if q.from_task_id else None
    task_ref = None
    if task is not None:
        task_project = await db.get(Project, task.project_id)
        task_ref = TaskRef(key=f"{task_project.key}-{task.number}", title=task.title)
    approver = await can_approve(db, user, q)
    draft = None
    if approver and q.draft_md is not None:
        agent = await db.get(Agent, q.draft_agent_id) if q.draft_agent_id else None
        draft = Draft(answer_md=q.draft_md, citations=[Citation(**c) for c in q.draft_citations or []],
                      agent=Ref(id=agent.id, name=agent.name) if agent else None)
    is_open = q.status in OPEN_STATUSES
    return QuestionOut(
        id=q.id, ref=ref_of(project, q), target=Target(key=project.key, name=project.name), title=q.title,
        body=q.body, context=q.context, status=q.status, answer_md=q.answer_md,
        citations=[Citation(**c) for c in q.citations or []], answer_source=q.answer_source,
        answered_by=await _who(db, q.answered_by_user_id, q.answered_by_agent_id), draft=draft,
        reject_reason=q.reject_reason, redacted=q.redacted, attempts=q.attempts, from_task=task_ref,
        asked_by=await _who(db, q.asked_by_user_id, q.asked_by_agent_id), kb_document_id=q.kb_document_id,
        created_at=q.created_at, answered_at=q.answered_at,
        can_answer=is_open and await can_answer_question(db, user, q), can_approve=approver,
        can_withdraw=is_open and (q.asked_by_user_id == user.id or user.role == Role.admin),
    )
