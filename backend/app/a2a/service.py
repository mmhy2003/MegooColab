"""Asking a project (A2A-1), suggestions from the KB and memory before routing (A2A-6), withdrawing."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
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
    from app.a2a.routing import route_question  # local: routing imports this module

    await route_question(db, q.id)  # dispatched by the caller after it commits (engine.dispatch_queued)
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


async def _answering(db: AsyncSession, q: Question) -> Who | None:
    agent_id = None
    if q.status == QuestionStatus.routed:
        agent_id = await db.scalar(
            select(AgentRun.agent_id).where(AgentRun.question_id == q.id, AgentRun.status.in_(ACTIVE_STATUSES))
            .order_by(AgentRun.created_at.desc()).limit(1)
        )
    elif q.status == QuestionStatus.draft:
        agent_id = q.draft_agent_id
    agent = await db.get(Agent, agent_id) if agent_id else None
    return await _who(db, agent.owner_id, agent.id) if agent else None


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
        answered_by=await _who(db, q.answered_by_user_id, q.answered_by_agent_id),
        answering=await _answering(db, q), draft=draft,
        reject_reason=q.reject_reason, redacted=q.redacted, attempts=q.attempts, from_task=task_ref,
        asked_by=await _who(db, q.asked_by_user_id, q.asked_by_agent_id), kb_document_id=q.kb_document_id,
        created_at=q.created_at, answered_at=q.answered_at,
        can_answer=is_open and await can_answer_question(db, user, q), can_approve=approver,
        can_withdraw=is_open and (q.asked_by_user_id == user.id or user.role == Role.admin),
    )


# -- answers -----------------------------------------------------------------------------------------


def _clean_answer(answer_md: str, citations: list) -> tuple[str, list[dict], bool]:
    """Validated, NUL-free, scrubbed answer text and citations (A2A-7)."""
    from pydantic import TypeAdapter, ValidationError

    from app.a2a.schemas import ANSWER_MAX
    from app.a2a.scrub import scrub

    text = strip_nul(answer_md or "").strip()
    if not 1 <= len(text) <= ANSWER_MAX:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_answer")
    try:
        parsed = TypeAdapter(list[Citation]).validate_python(citations or [])
    except ValidationError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_citations") from None
    if len(parsed) > 50 or any(c.end_line < c.start_line for c in parsed):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_citations")
    text, redacted = scrub(text)
    cites = []
    for c in parsed:
        path, changed = scrub(c.path)
        redacted = redacted or changed
        cites.append({"path": path, "start_line": c.start_line, "end_line": c.end_line})
    return text, cites, redacted


async def _mark_redacted(db: AsyncSession, q: Question, actor_id) -> None:
    q.redacted = True
    await audit.record(db, "a2a.answer.redacted", actor_id=actor_id, target_type="question", target_id=q.id)


async def on_answered(db: AsyncSession, q: Question) -> None:
    """The question has its final answer: file it in the target's KB, teach the memory, deliver it to the asking
    task, tell everyone (A2A-6). Idempotent: once filed, a second call does nothing."""
    if q.kb_document_id is not None:
        return
    from app.a2a.filing import file_answer
    from app.memory.sources import queue_extract

    await file_answer(db, q)
    await queue_extract(db, "answer", q.id)
    if q.from_task_id is not None:
        from app.tasks.service import record_event

        task = await db.get(Task, q.from_task_id)
        project = await db.get(Project, q.target_project_id)
        await record_event(db, task, q.answered_by_user_id, "question_answered",
                           {"question_id": str(q.id), "target_key": project.key, "number": q.number})
    await audit.record(db, "a2a.question.answered", actor_id=q.answered_by_user_id, target_type="question",
                       target_id=q.id, data={"source": q.answer_source})
    await notify(db, q)


async def _answer(db: AsyncSession, q: Question, text: str, cites: list[dict], source: str,
                  user_id: uuid.UUID | None, agent_id: uuid.UUID | None) -> None:
    q.answer_md, q.citations, q.answer_source = text, cites, source
    q.answered_by_user_id, q.answered_by_agent_id = user_id, agent_id
    q.draft_md, q.draft_citations, q.draft_agent_id = None, [], None
    q.status = QuestionStatus.answered
    q.answered_at = func.now()
    await db.flush()
    await db.refresh(q, ["answered_at"])
    await on_answered(db, q)


async def submit(db: AsyncSession, run: AgentRun, answer_md: str, citations: list) -> Question:
    """An answering run's answer (A2A-3/4): answered at once in auto mode, a draft for the owner in manual.
    Locks the question before the run, in the same order as a human answer or a withdrawal."""
    q = await lock_question(db, run.question_id)
    live = (
        await db.execute(select(AgentRun).where(AgentRun.id == run.id).with_for_update()
                         .execution_options(populate_existing=True))
    ).scalar_one_or_none()
    if live is None or live.status != RunStatus.running or live.question_id != q.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "run_not_running")
    if q.status != QuestionStatus.routed:
        raise HTTPException(status.HTTP_409_CONFLICT, "question_not_routed")
    text, cites, redacted = _clean_answer(answer_md, citations)
    agent = await db.get(Agent, live.agent_id)
    if redacted:
        await _mark_redacted(db, q, agent.owner_id)
    from app.agents.models import AnswerMode

    if agent.answer_mode == AnswerMode.auto:
        await _answer(db, q, text, cites, "agent", agent.owner_id, agent.id)
    else:
        q.draft_md, q.draft_citations, q.draft_agent_id = text, cites, agent.id
        q.status = QuestionStatus.draft
        await db.flush()
        await notify(db, q)
    return q


async def _locked_draft(db: AsyncSession, user: User, q: Question) -> Question:
    q = await lock_question(db, q.id)
    if q.status != QuestionStatus.draft:
        raise HTTPException(status.HTTP_409_CONFLICT, "not_a_draft")
    if not await can_approve(db, user, q):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    return q


async def approve(db: AsyncSession, user: User, q: Question, *, answer_md: str | None) -> Question:
    """The draft agent's owner (or an admin) approves a draft, optionally edited (A2A-4)."""
    q = await _locked_draft(db, user, q)
    agent = await db.get(Agent, q.draft_agent_id) if q.draft_agent_id else None
    text, cites, redacted = _clean_answer(answer_md if answer_md is not None else q.draft_md,
                                          list(q.draft_citations or []))
    if redacted:
        await _mark_redacted(db, q, user.id)
    await audit.record(db, "a2a.answer.approved", actor_id=user.id, target_type="question", target_id=q.id,
                       data={"edited": answer_md is not None})
    await _answer(db, q, text, cites, "agent", agent.owner_id if agent else user.id, agent.id if agent else None)
    return q


async def reject(db: AsyncSession, user: User, q: Question, *, reason: str) -> Question:
    """A rejected draft: its agent is excluded and the question goes back to the queue (A2A-4)."""
    q = await _locked_draft(db, user, q)
    reason = strip_nul(reason).strip()[:500]
    if not reason:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_reason")
    tried = list(q.tried_agent_ids or [])
    if q.draft_agent_id and str(q.draft_agent_id) not in tried:
        tried.append(str(q.draft_agent_id))
    q.tried_agent_ids = tried
    q.draft_md, q.draft_citations, q.draft_agent_id = None, [], None
    q.reject_reason = reason
    q.status = QuestionStatus.queued
    await db.flush()
    await audit.record(db, "a2a.answer.rejected", actor_id=user.id, target_type="question", target_id=q.id,
                       data={"reason": reason})
    await notify(db, q)
    from app.a2a.routing import route_question  # local: routing imports this module

    await route_question(db, q.id)  # dispatched by the caller after it commits (engine.dispatch_queued)
    return q


async def answer_by_human(
    db: AsyncSession, user: User, q: Question, *, answer_md: str, citations: list | None = None
) -> Question:
    """A member of the target project answers (A2A-5); an answering run still at work is cancelled."""
    q = await lock_question(db, q.id)
    if not await can_answer_question(db, user, q):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    if q.status == QuestionStatus.answered:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_answered")
    if q.status not in OPEN_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "not_open")
    text, cites, redacted = _clean_answer(answer_md, citations or [])
    if redacted:
        await _mark_redacted(db, q, user.id)
    q.status = QuestionStatus.answered  # before cancelling, so the run's end does not requeue the question
    await cancel_question_runs(db, q, user.id)
    await _answer(db, q, text, cites, "human", user.id, None)
    return q
