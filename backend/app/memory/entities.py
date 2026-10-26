"""Memory entities (MEM-1): the organization, teams, projects, people, agents and products."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.auth.models import Role, User
from app.memory.models import EntityKind, MemEntity, MemProductProject
from app.projects.access import accessible_project_ids
from app.projects.models import Project
from app.teams.models import Team

ORG_NAME = "Organization"
PRODUCT_NAME_MAX = 100
PRODUCT_DESCRIPTION_MAX = 2000

_COLUMN = {
    EntityKind.team: "team_id",
    EntityKind.project: "project_id",
    EntityKind.user: "user_id",
    EntityKind.agent: "agent_id",
}


async def _row_name(db: AsyncSession, kind: EntityKind, ref_id: uuid.UUID) -> str:
    if kind == EntityKind.team:
        row = await db.get(Team, ref_id)
        return row.name if row else "Team"
    if kind == EntityKind.project:
        row = await db.get(Project, ref_id)
        return f"{row.key} — {row.name}" if row else "Project"
    if kind == EntityKind.user:
        row = await db.get(User, ref_id)
        return row.name if row else "Person"
    row = await db.get(Agent, ref_id)
    return row.name if row else "Agent"


async def org_entity(db: AsyncSession) -> MemEntity:
    await db.execute(
        insert(MemEntity).values(id=uuid.uuid4(), kind=EntityKind.org, name=ORG_NAME).on_conflict_do_nothing()
    )
    return (await db.execute(select(MemEntity).where(MemEntity.kind == EntityKind.org))).scalar_one()


async def ensure_entity(db: AsyncSession, kind: EntityKind | str, ref_id: uuid.UUID | str | None = None) -> MemEntity:
    """The entity for a team, project, user or agent (created on first use, name kept current), or the org."""
    kind = EntityKind(kind)
    if kind == EntityKind.org:
        return await org_entity(db)
    if kind not in _COLUMN:
        raise ValueError(f"no row-backed entity of kind {kind}")
    ref = uuid.UUID(str(ref_id))
    column = getattr(MemEntity, _COLUMN[kind])
    name = await _row_name(db, kind, ref)
    await db.execute(
        insert(MemEntity)
        .values(id=uuid.uuid4(), kind=kind, name=name, **{_COLUMN[kind]: ref})
        .on_conflict_do_nothing()
    )
    entity = (await db.execute(select(MemEntity).where(column == ref))).scalar_one()
    if entity.name != name:
        entity.name = name
    return entity


async def ensure_core_entities(db: AsyncSession) -> None:
    """The org entity and one per team and project. Idempotent."""
    await org_entity(db)
    await db.execute(
        text(
            "INSERT INTO mem_entities (id, kind, team_id, name, description) "
            "SELECT gen_random_uuid(), 'team', t.id, t.name, '' FROM teams t "
            "WHERE NOT EXISTS (SELECT 1 FROM mem_entities e WHERE e.team_id = t.id) ON CONFLICT DO NOTHING"
        )
    )
    await db.execute(
        text(
            "INSERT INTO mem_entities (id, kind, project_id, name, description) "
            "SELECT gen_random_uuid(), 'project', p.id, p.key || ' — ' || p.name, '' FROM projects p "
            "WHERE NOT EXISTS (SELECT 1 FROM mem_entities e WHERE e.project_id = p.id) ON CONFLICT DO NOTHING"
        )
    )


# -- products ----------------------------------------------------------------------------------------


def _require_product_editor(user: User) -> None:
    if user.role not in (Role.admin, Role.manager):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")


def _clean(name: str | None, description: str | None) -> tuple[str | None, str | None]:
    if name is not None:
        name = name.replace("\x00", "").strip()
        if not 1 <= len(name) <= PRODUCT_NAME_MAX:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_name")
    if description is not None:
        description = description.replace("\x00", "")
        if len(description) > PRODUCT_DESCRIPTION_MAX:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "too_large")
    return name, description


async def _set_projects(db: AsyncSession, user: User, product: MemEntity, project_ids: list) -> None:
    ids = {uuid.UUID(str(p)) for p in project_ids}
    allowed = await accessible_project_ids(db, user)
    existing = set((await db.execute(select(Project.id).where(Project.id.in_(ids)))).scalars()) if ids else set()
    if ids - existing or (allowed is not None and ids - allowed):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project_not_found")
    await db.execute(delete(MemProductProject).where(MemProductProject.product_entity_id == product.id))
    db.add_all(MemProductProject(product_entity_id=product.id, project_id=p) for p in ids)
    await db.flush()


async def get_product(db: AsyncSession, product_id: uuid.UUID) -> MemEntity:
    product = await db.get(MemEntity, product_id)
    if product is None or product.kind != EntityKind.product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "product_not_found")
    return product


async def create_product(db: AsyncSession, user: User, name: str, description: str, project_ids: list) -> MemEntity:
    _require_product_editor(user)
    name, description = _clean(name, description or "")
    product = MemEntity(id=uuid.uuid4(), kind=EntityKind.product, name=name, description=description)
    db.add(product)
    await db.flush()
    await _set_projects(db, user, product, project_ids)
    return product


async def update_product(
    db: AsyncSession,
    user: User,
    product_id: uuid.UUID,
    *,
    name: str | None,
    description: str | None,
    project_ids: list | None,
) -> MemEntity:
    _require_product_editor(user)
    product = await get_product(db, product_id)
    name, description = _clean(name, description)
    if name is not None:
        product.name = name
    if description is not None:
        product.description = description
    if project_ids is not None:
        await _set_projects(db, user, product, project_ids)
    await db.flush()
    return product


async def delete_product(db: AsyncSession, user: User, product_id: uuid.UUID) -> None:
    _require_product_editor(user)
    await db.delete(await get_product(db, product_id))
    await db.flush()


async def product_project_ids(db: AsyncSession, product_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db.execute(
        select(MemProductProject.project_id).where(MemProductProject.product_entity_id == product_id)
    )
    return set(rows.scalars())
