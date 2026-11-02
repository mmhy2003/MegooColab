import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import select

from app.a2a import service
from app.a2a.models import Question, QuestionStatus
from app.a2a.schemas import (
    AnswerIn,
    ApproveIn,
    AskIn,
    AskQuestionOut,
    QuestionOut,
    RejectIn,
    SuggestIn,
    Suggestion,
    Target,
    TargetAgent,
)
from app.a2a import routing
from app.runner.registry import WORKFLOW_CAPABILITY, registry
from app.auth.deps import AuthedUser
from app.core.db import DbSession
from app.notifications.service import read_by_acting
from app.projects.access import accessible_project_ids, get_project_for
from app.projects.models import Project, ProjectStatus
from app.ratelimit.deps import check_ai
from app.tasks.service import get_task_for
from app.workflow import engine

router = APIRouter(tags=["questions"])

LIST_LIMIT = 100


@router.get("/api/questions/targets")
async def targets(_user: AuthedUser, db: DbSession) -> list[Target]:
    """Every project can be asked (A2A-1) except an archived one, so their keys and names are listed for addressing."""
    rows = await db.execute(
        select(Project.key, Project.name).where(Project.status != ProjectStatus.archived).order_by(Project.key)
    )
    return [Target(key=k, name=n) for k, n in rows]


@router.get("/api/questions/targets/{key}/agents")
async def target_agents(key: str, _user: AuthedUser, db: DbSession) -> list[TargetAgent]:
    """The agents that can answer the project's questions, for the asker to choose from: free, busy or offline."""
    project = await service.project_by_key(db, key)
    out = []
    for a in await service.project_agents(db, project.id):
        online = registry.is_available(a.id) and registry.agent_supports(a.id, WORKFLOW_CAPABILITY)
        busy = online and await routing.active_runs(db, a.id) >= a.max_concurrent_runs
        out.append(TargetAgent(id=a.id, name=a.name, program=a.program,
                               state="offline" if not online else "busy" if busy else "free"))
    return out


@router.post("/api/questions/suggest")
async def suggest(body: SuggestIn, request: Request, user: AuthedUser, db: DbSession) -> list[Suggestion]:
    await check_ai(request)  # suggestions embed the question
    project = await service.project_by_key(db, body.project_key)
    return await service.suggest(db, user, project.id, body.body)


@router.post("/api/questions", status_code=status.HTTP_201_CREATED)
async def ask(body: AskIn, request: Request, user: AuthedUser, db: DbSession) -> AskQuestionOut:
    await check_ai(request)  # asking looks for existing answers first, which embeds the question
    q, suggestions = await service.ask(
        db, user, project_key=body.project_key, body=body.body, title=body.title, context=body.context,
        task_key=body.task_key, prefer_agent_id=body.prefer_agent_id, prefer_program=body.prefer_program,
        if_busy=body.if_busy,
    )
    out = AskQuestionOut(question=await service.question_out(db, user, q), suggestions=suggestions)
    await engine.dispatch_queued(db)  # an answering run may have been queued on a live runner
    return out


@router.get("/api/questions")
async def list_questions(
    user: AuthedUser,
    db: DbSession,
    box: str = Query("mine", pattern="^(mine|incoming)$"),
    project: str | None = None,
    status_: Annotated[QuestionStatus | None, Query(alias="status")] = None,
) -> list[QuestionOut]:
    stmt = select(Question).order_by(Question.created_at.desc()).limit(LIST_LIMIT)
    if box == "mine":
        stmt = stmt.where(Question.asked_by_user_id == user.id)
    else:
        allowed = await accessible_project_ids(db, user)
        if allowed is not None:
            stmt = stmt.where(Question.target_project_id.in_(allowed))
    if project:
        target = await get_project_for(db, user, project) if box == "incoming" else await service.project_by_key(db, project)
        stmt = stmt.where(Question.target_project_id == target.id)
    if status_ is not None:
        stmt = stmt.where(Question.status == status_)
    return [await service.question_out(db, user, q) for q in (await db.execute(stmt)).scalars()]


@router.get("/api/questions/{question_id}")
async def get_question(question_id: uuid.UUID, user: AuthedUser, db: DbSession) -> QuestionOut:
    return await service.question_out(db, user, await service.get_question_for(db, user, question_id))


async def _acted(db, user_id: uuid.UUID, question_id: uuid.UUID) -> None:
    """The person dealt with the question: what they were told about it is read."""
    await read_by_acting(db, user_id, link=f"/questions/{question_id}")


@router.post("/api/questions/{question_id}/withdraw")
async def withdraw(question_id: uuid.UUID, user: AuthedUser, db: DbSession) -> QuestionOut:
    q = await service.get_question_for(db, user, question_id)
    out = await service.question_out(db, user, await service.withdraw(db, user, q))
    await _acted(db, user.id, question_id)
    return out


@router.post("/api/questions/{question_id}/approve")
async def approve(question_id: uuid.UUID, body: ApproveIn, user: AuthedUser, db: DbSession) -> QuestionOut:
    q = await service.get_question_for(db, user, question_id)
    out = await service.question_out(db, user, await service.approve(db, user, q, answer_md=body.answer_md))
    await _acted(db, user.id, question_id)
    return out


@router.post("/api/questions/{question_id}/reject")
async def reject(question_id: uuid.UUID, body: RejectIn, user: AuthedUser, db: DbSession) -> QuestionOut:
    q = await service.get_question_for(db, user, question_id)
    out = await service.question_out(db, user, await service.reject(db, user, q, reason=body.reason))
    await _acted(db, user.id, question_id)
    await engine.dispatch_queued(db)  # the question may have been routed to another agent
    return out


@router.post("/api/questions/{question_id}/answer")
async def answer(question_id: uuid.UUID, body: AnswerIn, user: AuthedUser, db: DbSession) -> QuestionOut:
    q = await service.get_question_for(db, user, question_id)
    citations = [c.model_dump() for c in body.citations]
    out = await service.question_out(
        db, user, await service.answer_by_human(db, user, q, answer_md=body.answer_md, citations=citations)
    )
    await _acted(db, user.id, question_id)
    return out


@router.get("/api/tasks/{key}/questions")
async def task_questions(key: str, user: AuthedUser, db: DbSession) -> list[QuestionOut]:
    task, _ = await get_task_for(db, user, key)
    rows = await db.execute(
        select(Question).where(Question.from_task_id == task.id).order_by(Question.created_at.desc())
    )
    return [await service.question_out(db, user, q) for q in rows.scalars()]

