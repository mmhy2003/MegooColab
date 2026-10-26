import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.a2a import service
from app.a2a.models import Question, QuestionStatus
from app.a2a.schemas import AskIn, AskOut, QuestionOut, SuggestIn, Suggestion, Target
from app.auth.deps import AuthedUser
from app.core.db import DbSession
from app.projects.access import accessible_project_ids, get_project_for
from app.projects.models import Project
from app.tasks.service import get_task_for
from app.workflow import engine

router = APIRouter(tags=["questions"])

LIST_LIMIT = 100


@router.get("/api/questions/targets")
async def targets(_user: AuthedUser, db: DbSession) -> list[Target]:
    """Every project can be asked (A2A-1), so every project's key and name is listed for addressing."""
    rows = await db.execute(select(Project.key, Project.name).order_by(Project.key))
    return [Target(key=k, name=n) for k, n in rows]


@router.post("/api/questions/suggest")
async def suggest(body: SuggestIn, user: AuthedUser, db: DbSession) -> list[Suggestion]:
    project = await service.project_by_key(db, body.project_key)
    return await service.suggest(db, user, project.id, body.body)


@router.post("/api/questions", status_code=status.HTTP_201_CREATED)
async def ask(body: AskIn, user: AuthedUser, db: DbSession) -> AskOut:
    q, suggestions = await service.ask(
        db, user, project_key=body.project_key, body=body.body, title=body.title, context=body.context,
        task_key=body.task_key,
    )
    out = AskOut(question=await service.question_out(db, user, q), suggestions=suggestions)
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


@router.post("/api/questions/{question_id}/withdraw")
async def withdraw(question_id: uuid.UUID, user: AuthedUser, db: DbSession) -> QuestionOut:
    q = await service.get_question_for(db, user, question_id)
    return await service.question_out(db, user, await service.withdraw(db, user, q))


@router.get("/api/tasks/{key}/questions")
async def task_questions(key: str, user: AuthedUser, db: DbSession) -> list[QuestionOut]:
    task, _ = await get_task_for(db, user, key)
    rows = await db.execute(
        select(Question).where(Question.from_task_id == task.id).order_by(Question.created_at.desc())
    )
    return [await service.question_out(db, user, q) for q in rows.scalars()]

