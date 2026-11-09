"""Deleting a task, for people (REST) and agents (MCP) alike: its reporter or a project manager may, its runs stop
first, and its uploads go once the deletion commits."""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.service import stop_runs_before_delete
from app.auth.models import User
from app.projects.access import can_manage_project, project_team_ids
from app.projects.models import Project
from app.sprints.service import snapshot_if_active
from app.tasks import service, uploads
from app.tasks.models import Task
from app.teams.service import user_team_ids


async def remove_task(db: AsyncSession, user: User, project: Project, task: Task) -> None:
    if task.reporter_id != user.id and not can_manage_project(
        user, await project_team_ids(db, project.id), await user_team_ids(db, user.id)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    sprint_id = task.sprint_id
    await stop_runs_before_delete(db, service.deleted_with(task))
    uploads.remove_after_commit(db, (await db.execute(service.deleted_with(task))).scalars().all())
    await service.task_changed(db, task, "task.deleted")
    await service.delete_task(db, task)
    await snapshot_if_active(db, sprint_id)
