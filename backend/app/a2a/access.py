"""Who sees and answers a question (A2A-7): the target project's members, the asker, and members of the asking
task's project. Anyone else is told the question does not exist."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.a2a.models import OPEN_STATUSES, Question
from app.auth.models import Role, User
from app.projects.access import accessible_project_ids
from app.tasks.models import Task

OPEN_QUESTION_CAP = 20


async def can_read_question(db: AsyncSession, user: User, q: Question) -> bool:
    if user.role == Role.admin or q.asked_by_user_id == user.id:
        return True
    allowed = await accessible_project_ids(db, user) or set()
    if q.target_project_id in allowed:
        return True
    if q.from_task_id is not None:
        project_id = await db.scalar(select(Task.project_id).where(Task.id == q.from_task_id))
        return project_id in allowed
    return False


async def can_answer_question(db: AsyncSession, user: User, q: Question) -> bool:
    """Non-viewer members of the target project, and admins (A2A-5)."""
    if user.role == Role.admin:
        return True
    if user.role == Role.viewer:
        return False
    return q.target_project_id in (await accessible_project_ids(db, user) or set())


async def open_question_count(db: AsyncSession, user: User) -> int:
    return await db.scalar(
        select(func.count()).select_from(Question).where(
            Question.asked_by_user_id == user.id, Question.status.in_(OPEN_STATUSES)
        )
    )
