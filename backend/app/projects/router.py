import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.service import stop_runs_before_delete
from app.audit import service as audit
from app.auth.deps import AuthedUser
from app.auth.models import Role
from app.core.db import DbSession
from app.core.events import Event, publish
from app.projects import service
from app.projects.access import accessible_project_ids, get_project_for, require_manage
from app.projects.models import BoardColumn, Label, Project, ProjectRepository
from app.projects.schemas import (
    ColumnIn,
    ColumnOrderIn,
    ColumnOut,
    ColumnPatch,
    LabelIn,
    LabelOut,
    LabelPatch,
    ProjectIn,
    ProjectOut,
    ProjectPatch,
    RepoIn,
    RepoOut,
    RepoPatch,
)
from app.tasks.models import Task

router = APIRouter(prefix="/api/projects", tags=["projects"])


async def _project_changed(db: AsyncSession, project: Project, kind: str = "project.updated") -> None:
    await publish(db, Event(type=kind, project_id=project.id))


async def _flush_or_409(db: AsyncSession, detail: str) -> None:
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, detail)


async def _managed(db: AsyncSession, user, ref: str) -> Project:
    project = await get_project_for(db, user, ref, write=True)
    await require_manage(db, user, project)
    return project


# ---- projects ---------------------------------------------------------------


@router.get("")
async def list_projects(user: AuthedUser, db: DbSession) -> list[ProjectOut]:
    allowed = await accessible_project_ids(db, user)
    stmt = select(Project).order_by(Project.name)
    if allowed is not None:
        stmt = stmt.where(Project.id.in_(allowed))
    return [await service.project_out(db, p) for p in (await db.execute(stmt)).scalars()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectIn, user: AuthedUser, db: DbSession) -> ProjectOut:
    if user.role not in (Role.admin, Role.manager):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    team_ids = set(body.team_ids)
    await service.check_team_ids(db, user, team_ids)
    project = Project(key=body.key, name=body.name, description=body.description, created_by=user.id)
    db.add(project)
    await _flush_or_409(db, "project_key_taken")
    await service.set_project_teams(db, project, team_ids)
    await service.create_default_columns(db, project)
    await db.flush()
    await audit.record(db, "project.created", actor_id=user.id, target_type="project", target_id=project.id)
    await _project_changed(db, project)
    return await service.project_out(db, project)


@router.get("/{ref}")
async def get_project(ref: str, user: AuthedUser, db: DbSession) -> ProjectOut:
    return await service.project_out(db, await get_project_for(db, user, ref))


@router.patch("/{ref}")
async def update_project(ref: str, body: ProjectPatch, user: AuthedUser, db: DbSession) -> ProjectOut:
    project = await _managed(db, user, ref)
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.sprints_enabled is not None:
        project.sprints_enabled = body.sprints_enabled
    if body.team_ids is not None:
        new_ids = set(body.team_ids)
        added = new_ids - await service.project_team_ids(db, project.id)
        await service.check_team_ids(db, user, added)
        await service.set_project_teams(db, project, new_ids)
    await db.flush()
    await _project_changed(db, project)
    return await service.project_out(db, project)


@router.delete("/{ref}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(ref: str, user: AuthedUser, db: DbSession) -> None:
    project = await get_project_for(db, user, ref, write=True)
    if user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    await stop_runs_before_delete(db, select(Task.id).where(Task.project_id == project.id))
    await _project_changed(db, project)
    await db.delete(project)
    await audit.record(db, "project.deleted", actor_id=user.id, target_type="project", target_id=project.id,
                       data={"key": project.key})


# ---- columns ----------------------------------------------------------------


@router.get("/{ref}/columns")
async def list_columns(ref: str, user: AuthedUser, db: DbSession) -> list[ColumnOut]:
    project = await get_project_for(db, user, ref)
    return await service.columns_out(db, project.id)


@router.post("/{ref}/columns", status_code=status.HTTP_201_CREATED)
async def add_column(ref: str, body: ColumnIn, user: AuthedUser, db: DbSession) -> ColumnOut:
    project = await _managed(db, user, ref)
    cols = await service.list_columns(db, project.id)
    col = BoardColumn(project_id=project.id, name=body.name, category=body.category,
                      position=(cols[-1].position + 1) if cols else 0)
    db.add(col)
    await db.flush()
    await _project_changed(db, project, "columns.updated")
    return ColumnOut.model_validate(col)


@router.patch("/{ref}/columns/{column_id}")
async def update_column(ref: str, column_id: uuid.UUID, body: ColumnPatch, user: AuthedUser, db: DbSession) -> ColumnOut:
    project = await _managed(db, user, ref)
    col = await service.get_column_or_404(db, project, column_id)
    if body.category is not None and body.category != col.category:
        others = [c.category for c in await service.list_columns(db, project.id) if c.id != col.id]
        service.ensure_required_categories([*others, body.category])
        col.category = body.category
    if body.name is not None:
        col.name = body.name
    await _project_changed(db, project, "columns.updated")
    return ColumnOut.model_validate(col)


@router.put("/{ref}/columns/order")
async def reorder_columns(ref: str, body: ColumnOrderIn, user: AuthedUser, db: DbSession) -> list[ColumnOut]:
    project = await _managed(db, user, ref)
    cols = {c.id: c for c in await service.list_columns(db, project.id)}
    if len(body.column_ids) != len(cols) or set(body.column_ids) != set(cols):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "must_list_every_column")
    for i, cid in enumerate(body.column_ids):
        cols[cid].position = i
    await db.flush()
    await _project_changed(db, project, "columns.updated")
    return await service.columns_out(db, project.id)


@router.delete("/{ref}/columns/{column_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_column(
    ref: str, column_id: uuid.UUID, user: AuthedUser, db: DbSession, move_to: uuid.UUID | None = None
) -> None:
    project = await _managed(db, user, ref)
    col = await service.get_column_or_404(db, project, column_id)
    others = [c for c in await service.list_columns(db, project.id) if c.id != col.id]
    service.ensure_required_categories([c.category for c in others])
    await service.move_column_tasks(db, project, col, move_to)
    await db.delete(col)
    await _project_changed(db, project, "columns.updated")


# ---- repositories -----------------------------------------------------------


async def _repo(db: AsyncSession, project: Project, repo_id: uuid.UUID) -> ProjectRepository:
    repo = await db.get(ProjectRepository, repo_id)
    if repo is None or repo.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "repository_not_found")
    return repo


@router.get("/{ref}/repositories")
async def list_repositories(ref: str, user: AuthedUser, db: DbSession) -> list[RepoOut]:
    project = await get_project_for(db, user, ref)
    rows = await db.execute(
        select(ProjectRepository).where(ProjectRepository.project_id == project.id).order_by(ProjectRepository.name)
    )
    return [RepoOut.model_validate(r) for r in rows.scalars()]


@router.post("/{ref}/repositories", status_code=status.HTTP_201_CREATED)
async def add_repository(ref: str, body: RepoIn, user: AuthedUser, db: DbSession) -> RepoOut:
    project = await _managed(db, user, ref)
    repo = ProjectRepository(project_id=project.id, **body.model_dump())
    db.add(repo)
    await db.flush()
    await _project_changed(db, project)
    return RepoOut.model_validate(repo)


@router.patch("/{ref}/repositories/{repo_id}")
async def update_repository(ref: str, repo_id: uuid.UUID, body: RepoPatch, user: AuthedUser, db: DbSession) -> RepoOut:
    project = await _managed(db, user, ref)
    repo = await _repo(db, project, repo_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(repo, field, value)
    await _project_changed(db, project)
    return RepoOut.model_validate(repo)


@router.delete("/{ref}/repositories/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository(ref: str, repo_id: uuid.UUID, user: AuthedUser, db: DbSession) -> None:
    project = await _managed(db, user, ref)
    await db.delete(await _repo(db, project, repo_id))
    await _project_changed(db, project)


# ---- labels -----------------------------------------------------------------


async def _label(db: AsyncSession, project: Project, label_id: uuid.UUID) -> Label:
    label = await db.get(Label, label_id)
    if label is None or label.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "label_not_found")
    return label


@router.get("/{ref}/labels")
async def list_labels(ref: str, user: AuthedUser, db: DbSession) -> list[LabelOut]:
    project = await get_project_for(db, user, ref)
    rows = await db.execute(select(Label).where(Label.project_id == project.id).order_by(Label.name))
    return [LabelOut.model_validate(r) for r in rows.scalars()]


@router.post("/{ref}/labels", status_code=status.HTTP_201_CREATED)
async def add_label(ref: str, body: LabelIn, user: AuthedUser, db: DbSession) -> LabelOut:
    project = await _managed(db, user, ref)
    label = Label(project_id=project.id, name=body.name, color=body.color.upper())
    db.add(label)
    await _flush_or_409(db, "label_name_taken")
    await _project_changed(db, project)
    return LabelOut.model_validate(label)


@router.patch("/{ref}/labels/{label_id}")
async def update_label(ref: str, label_id: uuid.UUID, body: LabelPatch, user: AuthedUser, db: DbSession) -> LabelOut:
    project = await _managed(db, user, ref)
    label = await _label(db, project, label_id)
    if body.name is not None:
        label.name = body.name
    if body.color is not None:
        label.color = body.color.upper()
    await _flush_or_409(db, "label_name_taken")
    await _project_changed(db, project)
    return LabelOut.model_validate(label)


@router.delete("/{ref}/labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_label(ref: str, label_id: uuid.UUID, user: AuthedUser, db: DbSession) -> None:
    project = await _managed(db, user, ref)
    await db.delete(await _label(db, project, label_id))
    await _project_changed(db, project)
