"""Needs you: workflows waiting for a person, answers waiting to be sent, questions no agent could answer, and (under
Mine) unread mentions. Addressed to the same people the notifications go to (NOT-1)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.a2a.models import Question, QuestionStatus
from app.agents.models import Agent
from app.auth.models import Role, User
from app.dashboard.schemas import NeedItem
from app.dashboard.scope import Scope, task_link
from app.notifications.models import Kind, Notification
from app.projects.models import Project, ProjectTeam
from app.tasks.models import Task
from app.teams.models import TeamMember
from app.workflow.models import QuestionStatus as WorkflowQuestionStatus
from app.workflow.models import TaskWorkflow, WorkflowQuestion, WorkflowStatus

NEEDS_SHOWN = 10


def _owner_of(agent_id):
    return select(Agent.owner_id).where(Agent.id == agent_id).scalar_subquery()


async def _names(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict((await db.execute(select(User.id, User.name).where(User.id.in_(ids)))).all())


async def _workflow_waits(db: AsyncSession, scope: Scope) -> list[tuple[NeedItem, list[uuid.UUID]]]:
    owner = _owner_of(func.coalesce(TaskWorkflow.agent_id, Task.assignee_agent_id))
    stmt = (
        select(Task.id, Task.number, Task.title, Project.key, TaskWorkflow.needs, TaskWorkflow.escalation_reason,
               TaskWorkflow.pr_url, func.coalesce(TaskWorkflow.waiting_since, TaskWorkflow.updated_at),
               owner, Task.assignee_user_id)
        .join(Task, Task.id == TaskWorkflow.task_id).join(Project, Project.id == Task.project_id)
        .where(TaskWorkflow.status == WorkflowStatus.waiting_human, TaskWorkflow.needs.is_not(None),
               scope.in_projects(Task.project_id))
    )
    if scope.name == "mine":
        stmt = stmt.where(or_(owner == scope.user.id, Task.assignee_user_id == scope.user.id))
    rows = (await db.execute(stmt)).all()
    asking = [r[0] for r in rows if r[4] == "question"]
    questions: dict[uuid.UUID, str] = {}
    if asking:
        questions = dict((await db.execute(
            select(WorkflowQuestion.task_id, WorkflowQuestion.body)
            .where(WorkflowQuestion.task_id.in_(asking), WorkflowQuestion.status == WorkflowQuestionStatus.open)
            .order_by(WorkflowQuestion.task_id, WorkflowQuestion.created_at.desc())
            .ext(distinct_on(WorkflowQuestion.task_id))
        )).all())
    out = []
    for task_id, number, title, key, needs, reason, pr_url, since, owner_id, assignee_id in rows:
        detail = {"question": questions.get(task_id), "escalation": reason, "human_code_review": pr_url}.get(needs)
        item = NeedItem(kind=needs, ref=f"{key}-{number}", title=title, detail=detail, since=since,
                        link=task_link(key, number))
        out.append((item, [u for u in dict.fromkeys((owner_id, assignee_id)) if u is not None]))
    return out


async def _draft_answers(db: AsyncSession, scope: Scope) -> list[tuple[NeedItem, list[uuid.UUID]]]:
    owner = _owner_of(Question.draft_agent_id)
    stmt = (
        select(Question.id, Question.number, Question.title, Question.updated_at, Project.key, owner)
        .join(Project, Project.id == Question.target_project_id)
        .where(Question.status == QuestionStatus.draft, scope.in_projects(Question.target_project_id))
    )
    if scope.name == "mine":
        stmt = stmt.where(owner == scope.user.id)
    return [
        (NeedItem(kind="draft_answer", ref=f"{key}-Q{number}", title=title, since=since, link=f"/questions/{qid}"),
         [owner_id] if owner_id else [])
        for qid, number, title, since, key, owner_id in (await db.execute(stmt)).all()
    ]


async def _needs_a_person(db: AsyncSession, scope: Scope) -> list[NeedItem]:
    """Questions routing gave up on: the target project's members who can answer (not viewers) are asked."""
    if scope.name == "mine" and scope.user.role == Role.viewer:
        return []
    stmt = (
        select(Question.id, Question.number, Question.title, Question.updated_at, Project.key)
        .join(Project, Project.id == Question.target_project_id)
        .where(Question.status == QuestionStatus.needs_human, scope.in_projects(Question.target_project_id))
    )
    if scope.name == "mine":
        stmt = stmt.where(exists(
            select(ProjectTeam.project_id).join(TeamMember, TeamMember.team_id == ProjectTeam.team_id)
            .where(ProjectTeam.project_id == Question.target_project_id, TeamMember.user_id == scope.user.id)
        ))
    return [
        NeedItem(kind="needs_human", ref=f"{key}-Q{number}", title=title, since=since, link=f"/questions/{qid}",
                 waiting_for=[f"anyone on {key}"] if scope.name != "mine" else [])
        for qid, number, title, since, key in (await db.execute(stmt)).all()
    ]


async def _mentions(db: AsyncSession, scope: Scope) -> list[NeedItem]:
    stmt = (
        select(Notification.id, Notification.title, Notification.body, Notification.link, Notification.created_at,
               Project.key, Task.number)
        .outerjoin(Task, Task.id == Notification.task_id).outerjoin(Project, Project.id == Task.project_id)
        .where(Notification.user_id == scope.user.id, Notification.kind == Kind.mentioned,
               Notification.read_at.is_(None),
               or_(Notification.project_id.is_(None), scope.in_projects(Notification.project_id)))
    )
    return [
        NeedItem(kind="mention", ref=f"{key}-{number}" if key else "", title=title, detail=body, since=since,
                 link=link, notification_id=nid)
        for nid, title, body, link, since, key, number in (await db.execute(stmt)).all()
    ]


async def needs(db: AsyncSession, scope: Scope, limit: int = NEEDS_SHOWN) -> tuple[list[NeedItem], int, int]:
    """(the longest-waiting rows, how many wait in all, how many of them have waited over a day)."""
    addressed = await _workflow_waits(db, scope) + await _draft_answers(db, scope)
    if scope.name != "mine":
        names = await _names(db, {u for _, ids in addressed for u in ids})
        for item, ids in addressed:
            item.waiting_for = [names[u] for u in ids if u in names]
    items = [item for item, _ in addressed] + await _needs_a_person(db, scope)
    if scope.name == "mine":
        items += await _mentions(db, scope)
    items.sort(key=lambda n: n.since)
    day_ago = datetime.now(UTC) - timedelta(days=1)
    return items[:limit], len(items), sum(1 for n in items if n.since < day_ago)

