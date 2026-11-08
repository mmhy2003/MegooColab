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


async def can_act_on_task(db: AsyncSession, user: User, task_id) -> bool:
    """May the user act on the task's workflow (WF-6: the agent's owner, a manager, a connect-only assignee)?"""
    from app.agents.models import Agent
    from app.projects.models import Project
    from app.tasks.models import Task
    from app.workflow import engine  # local: the engine imports the a2a modules lazily
    from app.workflow.models import TaskWorkflow

    task = await db.get(Task, task_id) if task_id else None
    if task is None:
        return False
    wf = await db.get(TaskWorkflow, task.id)
    agent_id = task.assignee_agent_id or (wf.agent_id if wf else None)
    owner_id = await db.scalar(select(Agent.owner_id).where(Agent.id == agent_id)) if agent_id else None
    manages = await engine.manages(db, user, await db.get(Project, task.project_id))
    return engine.can_act(user, task, wf, manages, owner_id)


async def open_question_count(db: AsyncSession, user: User) -> int:
    return await db.scalar(
        select(func.count()).select_from(Question).where(
            Question.asked_by_user_id == user.id, Question.status.in_(OPEN_STATUSES),
            # what an agent asks for a task counts against that task's limit (service.QUESTION_LIMIT), not here
            ~(Question.asked_by_agent_id.is_not(None) & Question.from_task_id.is_not(None)),
        )
    )
