import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.a2a.models import Question
from app.agent_runs.service import stop_runs_before_delete
from app.audit import service as audit
from app.auth.deps import AuthedUser
from app.auth.models import Role
from app.core.db import DbSession
from app.core.events import Event, publish
from app.kb import access as kb_access
from app.memory import entities as mem_entities
from app.memory.models import EntityKind
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.projects import lifecycle, service
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
    ProjectStatusIn,
    RepoConnection,
    RepoIn,
    RepoOut,
    RepoPatch,
    WorkflowCountOut,
)
from app.tasks import uploads
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
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    if org is not None:  # ADM-1: the organization's defaults for new projects
        project.finishing_option = org.default_finishing_option
        project.require_human_code_review = org.default_require_human_code_review
        project.sprints_enabled = org.default_sprints_enabled
        project.commit_docs_to_repo = org.default_commit_docs_to_repo
    db.add(project)
    await _flush_or_409(db, "project_key_taken")
    await service.set_project_teams(db, project, team_ids)
    await service.create_default_columns(db, project)
    await db.flush()
    await kb_access.space_for_project(db, project.id)
    await mem_entities.ensure_entity(db, EntityKind.project, project.id)
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
    if body.finishing_option is not None:
        project.finishing_option = body.finishing_option
    if body.require_human_code_review is not None:
        project.require_human_code_review = body.require_human_code_review
    if body.commit_docs_to_repo is not None:
        project.commit_docs_to_repo = body.commit_docs_to_repo
    if body.team_ids is not None:
        new_ids = set(body.team_ids)
        added = new_ids - await service.project_team_ids(db, project.id)
        await service.check_team_ids(db, user, added)
        await service.set_project_teams(db, project, new_ids)
    await db.flush()
    await _project_changed(db, project)
    return await service.project_out(db, project)


@router.put("/{ref}/status")
async def set_project_status(ref: str, body: ProjectStatusIn, user: AuthedUser, db: DbSession) -> ProjectOut:
    """Not through the write check: this is how a closed project is reopened."""
    project = await get_project_for(db, user, ref)
    await require_manage(db, user, project)
    if await lifecycle.set_status(db, user, project, body.status):
        await db.flush()
        await _project_changed(db, project)
    return await service.project_out(db, project)


@router.get("/{ref}/workflows-in-progress")
async def workflows_in_progress(ref: str, user: AuthedUser, db: DbSession) -> WorkflowCountOut:
    """What closing the project would pause, for the confirmation."""
    project = await get_project_for(db, user, ref)
    return WorkflowCountOut(count=len(await lifecycle.active_workflow_tasks(db, project.id)))


@router.delete("/{ref}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(ref: str, user: AuthedUser, db: DbSession) -> None:
    # any status: archiving a test project first and deleting it later is the usual path
    project = await get_project_for(db, user, ref)
    if user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    task_ids = select(Task.id).where(Task.project_id == project.id)
    # answering runs too: questions to an archived project carry on until it is deleted
    question_ids = select(Question.id).where(Question.target_project_id == project.id)
    await stop_runs_before_delete(db, task_ids, question_ids)
    uploads.remove_after_commit(db, (await db.execute(task_ids)).scalars().all())
    await _project_changed(db, project)
    await db.delete(project)
    # local: memory imports the task modules
    from app.memory.sources import queue_forget

    await queue_forget(db)  # what was learned only from this project's tasks and answers
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


async def _repo_out(db: AsyncSession, repo: ProjectRepository) -> RepoOut:
    from app.git.models import GitConnection  # local: git imports the project models

    out = RepoOut.model_validate(repo)
    conn = await db.get(GitConnection, repo.connection_id) if repo.connection_id else None
    out.connection = RepoConnection(id=conn.id, name=conn.name) if conn is not None else None
    return out


async def _check_connection(db: AsyncSession, connection_id: uuid.UUID | None) -> None:
    from app.git.models import GitConnection  # local: git imports the project models

    if connection_id is not None and await db.get(GitConnection, connection_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "git_connection_not_found")


@router.get("/{ref}/repositories")
async def list_repositories(ref: str, user: AuthedUser, db: DbSession) -> list[RepoOut]:
    project = await get_project_for(db, user, ref)
    rows = await db.execute(
        select(ProjectRepository).where(ProjectRepository.project_id == project.id).order_by(ProjectRepository.name)
    )
    return [await _repo_out(db, r) for r in rows.scalars()]


@router.post("/{ref}/repositories", status_code=status.HTTP_201_CREATED)
async def add_repository(ref: str, body: RepoIn, user: AuthedUser, db: DbSession) -> RepoOut:
    project = await _managed(db, user, ref)
    await _check_connection(db, body.connection_id)
    repo = ProjectRepository(project_id=project.id, **body.model_dump())
    db.add(repo)
    await db.flush()
    await _project_changed(db, project)
    return await _repo_out(db, repo)


@router.patch("/{ref}/repositories/{repo_id}")
async def update_repository(ref: str, repo_id: uuid.UUID, body: RepoPatch, user: AuthedUser, db: DbSession) -> RepoOut:
    project = await _managed(db, user, ref)
    repo = await _repo(db, project, repo_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(repo, field, value)
    if "connection_id" in body.model_fields_set:
        await _check_connection(db, body.connection_id)
        repo.connection_id = body.connection_id
    await db.flush()
    await _project_changed(db, project)
    return await _repo_out(db, repo)


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
