"""What each kind puts into the search index (Plan 9), built from the database, which stays the source of truth.

Every document carries `readers`, the permission tokens that may see it: `all`, `user:<id>`, `project:<id>` or
`space:<id>`. The search service turns a user into the same tokens at search time, so a permission change needs
no reindex. Only text already stored on the platform is indexed (NFR-2).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.a2a.models import Question
from app.agents.models import Agent, AgentBinding
from app.auth.models import User, UserStatus
from app.kb.models import KbDocument, KbSpace
from app.projects.models import BoardColumn, Label, Project
from app.tasks.models import Comment, Task, task_labels
from app.teams.models import Team, TeamMember

KINDS = ("task", "document", "project", "team", "person", "agent", "question")
MAX_COMMENTS_CHARS = 20_000


def doc_id(kind: str, id: uuid.UUID | str) -> str:
    return f"{kind}-{id}"


def _ts(at: datetime | None) -> int:
    return int(at.timestamp()) if at else 0


def _base(kind: str, id: uuid.UUID, **fields: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": doc_id(kind, id), "kind": kind, "key": "", "title": "", "body": "", "comments": "", "url": None,
        "readers": [], "project_id": None, "project_key": None, "status": None, "assignee": None, "type": None,
        "labels": [], "updated_at": 0, "card": None,
    }
    doc.update(fields)
    return doc


async def _task(db: AsyncSession, id: uuid.UUID) -> dict | None:
    task = await db.get(Task, id)
    if task is None:
        return None
    project = await db.get(Project, task.project_id)
    column = await db.get(BoardColumn, task.column_id)
    labels = (
        await db.execute(
            select(Label.name).join(task_labels, task_labels.c.label_id == Label.id)
            .where(task_labels.c.task_id == task.id).order_by(Label.name)
        )
    ).scalars().all()
    comments: list[str] = []
    size = 0
    rows = await db.execute(
        select(Comment.body_md).where(Comment.task_id == task.id).order_by(Comment.created_at.desc(), Comment.id)
    )
    for body in rows.scalars():
        if size + len(body) + 1 > MAX_COMMENTS_CHARS:
            break
        comments.append(body)
        size += len(body) + 1
    key = f"{project.key}-{task.number}"
    assignee = (
        f"user:{task.assignee_user_id}" if task.assignee_user_id
        else f"agent:{task.assignee_agent_id}" if task.assignee_agent_id else None
    )
    return _base(
        "task", task.id, key=key, title=task.title, body=task.description_md or "", comments="\n".join(comments),
        url=f"/projects/{project.key}/board?task={key}", readers=[f"project:{project.id}"],
        project_id=str(project.id), project_key=project.key, status=str(column.category) if column else None,
        assignee=assignee, type=str(task.type), labels=list(labels), updated_at=_ts(task.updated_at),
    )


async def _document(db: AsyncSession, id: uuid.UUID) -> dict | None:
    doc = await db.get(KbDocument, id)
    if doc is None:
        return None
    space = await db.get(KbSpace, doc.space_id)
    project = await db.get(Project, space.project_id) if space and space.project_id else None
    return _base(
        "document", doc.id, title=doc.title, body=doc.body_md or "", url=f"/kb/doc/{doc.id}",
        readers=[f"space:{doc.space_id}"], project_id=str(project.id) if project else None,
        project_key=project.key if project else None, updated_at=_ts(doc.updated_at),
    )


async def _project(db: AsyncSession, id: uuid.UUID) -> dict | None:
    project = await db.get(Project, id)
    if project is None:
        return None
    return _base(
        "project", project.id, key=project.key, title=project.name, body=project.description or "",
        url=f"/projects/{project.key}/board", readers=[f"project:{project.id}"], project_id=str(project.id),
        project_key=project.key, updated_at=_ts(project.updated_at),
    )


async def _team(db: AsyncSession, id: uuid.UUID) -> dict | None:
    team = await db.get(Team, id)
    if team is None:
        return None
    return _base(
        "team", team.id, title=team.name, body=team.description or "", url=f"/teams/{team.id}", readers=["all"],
        updated_at=_ts(team.updated_at),
    )


async def _person(db: AsyncSession, id: uuid.UUID) -> dict | None:
    user = await db.get(User, id)
    if user is None or user.status != UserStatus.active:
        return None
    teams = (
        await db.execute(
            select(Team.id, Team.name).join(TeamMember, TeamMember.team_id == Team.id)
            .where(TeamMember.user_id == user.id).order_by(Team.name)
        )
    ).all()
    return _base(
        "person", user.id, title=user.name, body=user.email, readers=["all"], updated_at=_ts(user.updated_at),
        card={"email": user.email, "teams": [{"id": str(t), "name": n} for t, n in teams]},
    )


async def _agent(db: AsyncSession, id: uuid.UUID) -> dict | None:
    agent = await db.get(Agent, id)
    if agent is None:
        return None
    owner = await db.get(User, agent.owner_id)
    projects = (
        await db.execute(
            select(Project.id, Project.key).join(AgentBinding, AgentBinding.project_id == Project.id)
            .where(AgentBinding.agent_id == agent.id).order_by(Project.key)
        )
    ).all()
    owner_name = owner.name if owner else ""
    return _base(
        "agent", agent.id, title=agent.name, body=owner_name, readers=["all"], updated_at=_ts(agent.created_at),
        card={"owner_name": owner_name, "projects": [{"id": str(p), "key": k} for p, k in projects]},
    )


async def _question(db: AsyncSession, id: uuid.UUID) -> dict | None:
    q = await db.get(Question, id)
    if q is None:
        return None
    target = await db.get(Project, q.target_project_id)
    readers = [f"project:{q.target_project_id}"]
    if q.from_task_id is not None:
        source = await db.scalar(select(Task.project_id).where(Task.id == q.from_task_id))
        if source is not None and f"project:{source}" not in readers:
            readers.append(f"project:{source}")
    if q.asked_by_user_id is not None:
        readers.append(f"user:{q.asked_by_user_id}")
    body = q.body + (f"\n\n{q.answer_md}" if q.answer_md else "")
    return _base(
        "question", q.id, key=f"{target.key}-Q{q.number}", title=q.title, body=body, url=f"/questions/{q.id}",
        readers=readers, project_id=str(target.id), project_key=target.key, status=str(q.status),
        updated_at=_ts(q.updated_at),
    )


_BUILDERS = {
    "task": _task, "document": _document, "project": _project, "team": _team, "person": _person,
    "agent": _agent, "question": _question,
}
_MODELS = {
    "task": Task, "document": KbDocument, "project": Project, "team": Team, "person": User, "agent": Agent,
    "question": Question,
}


async def build(db: AsyncSession, kind: str, id: uuid.UUID) -> dict | None:
    """The index document for one item, or None when it no longer exists or must not be indexed."""
    return await _BUILDERS[kind](db, id)


async def ids_of(db: AsyncSession, kind: str) -> AsyncIterator[uuid.UUID]:
    """Every indexable id of a kind, for rebuilds."""
    model = _MODELS[kind]
    stmt = select(model.id).order_by(model.id)
    if kind == "person":
        stmt = stmt.where(User.status == UserStatus.active)
    for (id,) in (await db.execute(stmt)).all():
        yield id
