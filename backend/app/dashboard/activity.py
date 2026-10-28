"""Recent activity: the latest task events in scope. Comments are left out (mentions already show), and so are a
working agent's streamed updates and question events, which would push everything else off the list in seconds."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.auth.models import User
from app.dashboard.schemas import ActivityRow
from app.dashboard.scope import Scope
from app.projects.models import BoardColumn, Project
from app.tasks.models import Task, TaskEvent

ACTIVITY_SHOWN = 8
STREAMED = ("agent_message", "agent_plan", "agent_tool", "agent_file_change", "agent_command", "agent_permission")
# keys in an event's data that hold an id worth a name: where the frontend's describeEvent looks
_COLUMN_KEYS, _USER_KEYS, _AGENT_KEYS = ("to_column", "from_column"), ("to", "from"), ("to_agent", "from_agent")


def _ids(data: dict, keys: tuple[str, ...]) -> set[uuid.UUID]:
    out = set()
    for key in keys:
        try:
            out.add(uuid.UUID(str(data[key])))
        except (KeyError, ValueError):
            pass
    return out


async def _named(db: AsyncSession, model, ids: set[uuid.UUID]) -> dict[str, str]:
    if not ids:
        return {}
    return {str(i): name for i, name in (await db.execute(select(model.id, model.name).where(model.id.in_(ids)))).all()}


async def activity(db: AsyncSession, scope: Scope, limit: int = ACTIVITY_SHOWN) -> list[ActivityRow]:
    rows = (await db.execute(
        select(TaskEvent, Project.key, Task.number)
        .join(Task, Task.id == TaskEvent.task_id).join(Project, Project.id == Task.project_id)
        .where(scope.in_projects(Task.project_id), scope.mine_tasks(), TaskEvent.kind.not_in(STREAMED),
               TaskEvent.kind.not_like("question.%"))
        .order_by(TaskEvent.created_at.desc(), TaskEvent.id.desc()).limit(limit)
    )).all()
    events = [e for e, _, _ in rows]
    agent_ids = set().union(*(_ids(e.data, ("agent_id", *_AGENT_KEYS)) for e in events)) if events else set()
    user_ids = set().union(*(_ids(e.data, _USER_KEYS) for e in events)) if events else set()
    user_ids |= {e.actor_user_id for e in events if e.actor_user_id}
    columns = set().union(*(_ids(e.data, _COLUMN_KEYS) for e in events)) if events else set()
    users, agents = await _named(db, User, user_ids), await _named(db, Agent, agent_ids)
    column_names = await _named(db, BoardColumn, columns)
    out = []
    for event, key, number in rows:
        data = event.data or {}
        names = {
            str(i): n for i in _ids(data, _COLUMN_KEYS) | _ids(data, _USER_KEYS) | _ids(data, _AGENT_KEYS)
            if (n := column_names.get(str(i)) or users.get(str(i)) or agents.get(str(i)))
        }
        actor = users.get(str(event.actor_user_id)) if event.actor_user_id else agents.get(str(data.get("agent_id")))
        out.append(ActivityRow(id=event.id, at=event.created_at, kind=event.kind, data=data, actor_name=actor,
                               task_key=f"{key}-{number}", names=names))
    return out
