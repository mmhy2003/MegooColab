import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.agent_runs.service import stop_runs_before_delete
from app.auth.deps import AuthedUser
from app.core.db import DbSession
from app.projects.access import can_manage_project, get_project_for, project_team_ids
from app.sprints.service import snapshot_if_active
from app.tasks import service, uploads
from app.tasks.models import Task, TaskLink, TaskType
from app.tasks.schemas import LinkIn, MoveIn, TaskCreate, TaskOut, TaskUpdate
from app.teams.service import user_team_ids
from app.workflow import engine
from app.workflow.models import WorkflowStatus

router = APIRouter(tags=["tasks"])


_changed = service.task_changed


@router.post("/api/projects/{ref}/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(ref: str, body: TaskCreate, user: AuthedUser, db: DbSession) -> TaskOut:
    project = await get_project_for(db, user, ref, write=True)
    task = await service.create_task(db, user, project, body)
    await _changed(db, task, "task.created")
    return await service.task_out(db, task, user)


@router.get("/api/projects/{ref}/tasks")
async def list_tasks(
    ref: str,
    user: AuthedUser,
    db: DbSession,
    type_: Annotated[TaskType | None, Query(alias="type")] = None,
    assignee: str | None = None,
    label: uuid.UUID | None = None,
    epic: uuid.UUID | None = None,
    sprint: str | None = None,
    column: uuid.UUID | None = None,
    q: str | None = None,
    needs_you: bool = False,
) -> list[TaskOut]:
    project = await get_project_for(db, user, ref)
    tasks = await service.list_tasks(
        db, project, type_=type_, assignee=assignee, label=label, epic=epic, sprint=sprint, column=column, q=q
    )
    out = await service.tasks_out(db, tasks, user)
    if needs_you:  # PROJ-7: waiting on a human the caller may answer for (same rule as WF-6)
        out = [t for t in out if t.workflow and t.workflow.status == WorkflowStatus.waiting_human and t.workflow.can_act]
    return out


@router.get("/api/tasks/{key}")
async def get_task(key: str, user: AuthedUser, db: DbSession) -> TaskOut:
    task, _ = await service.get_task_for(db, user, key)
    return (await service.tasks_out(db, [task], user))[0]


@router.patch("/api/tasks/{key}")
async def update_task(key: str, body: TaskUpdate, user: AuthedUser, db: DbSession) -> TaskOut:
    task, project = await service.get_task_for(db, user, key, write=True)
    await service.update_task(db, user, project, task, body)
    await _changed(db, task)
    await engine.dispatch_queued(db)
    return await service.task_out(db, task, user)


@router.delete("/api/tasks/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(key: str, user: AuthedUser, db: DbSession) -> None:
    task, project = await service.get_task_for(db, user, key, write=True)
    if task.reporter_id != user.id and not can_manage_project(
        user, await project_team_ids(db, project.id), await user_team_ids(db, user.id)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    sprint_id = task.sprint_id
    await stop_runs_before_delete(db, service.deleted_with(task))
    uploads.remove_after_commit(db, (await db.execute(service.deleted_with(task))).scalars().all())
    await _changed(db, task, "task.deleted")
    await service.delete_task(db, task)
    await snapshot_if_active(db, sprint_id)


@router.post("/api/tasks/{key}/move")
async def move_task(key: str, body: MoveIn, user: AuthedUser, db: DbSession) -> TaskOut:
    task, project = await service.get_task_for(db, user, key, write=True)
    await service.move_task(db, user, project, task, body)
    await _changed(db, task)
    await engine.dispatch_queued(db)  # a move into working may have started or resumed the workflow
    return await service.task_out(db, task, user)


@router.post("/api/tasks/{key}/links", status_code=status.HTTP_201_CREATED)
async def add_link(key: str, body: LinkIn, user: AuthedUser, db: DbSession) -> TaskOut:
    task, project = await service.get_task_for(db, user, key, write=True)
    link = await service.add_link(db, user, project, task, body.target_key, body.kind)
    await _changed(db, task)
    target = await db.get(Task, link.target_id)
    await _changed(db, target)
    return await service.task_out(db, task, user)


@router.delete("/api/tasks/{key}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_link(key: str, link_id: uuid.UUID, user: AuthedUser, db: DbSession) -> None:
    task, _ = await service.get_task_for(db, user, key, write=True)
    link = await db.get(TaskLink, link_id)
    if link is None or task.id not in (link.source_id, link.target_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "link_not_found")
    other = await db.get(Task, link.target_id if link.source_id == task.id else link.source_id)
    await db.delete(link)
    await _changed(db, task)
    if other is not None:
        await _changed(db, other)


@router.put("/api/tasks/{key}/watch", status_code=status.HTTP_204_NO_CONTENT)
async def watch(key: str, user: AuthedUser, db: DbSession) -> None:
    task, _ = await service.get_task_for(db, user, key)
    await service.add_watcher(db, task.id, user.id)


@router.delete("/api/tasks/{key}/watch", status_code=status.HTTP_204_NO_CONTENT)
async def unwatch(key: str, user: AuthedUser, db: DbSession) -> None:
    task, _ = await service.get_task_for(db, user, key)
    await service.remove_watcher(db, task.id, user.id)
