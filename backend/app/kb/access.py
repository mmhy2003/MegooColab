"""Knowledge Base access: reading follows space membership, writing also needs a non-viewer role.

Org space: every active user. Team space: the team's members. Project space: users with access to the
project. Admins read and write everything. A space the caller cannot read is reported as not found.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User
from app.kb.models import KbDocument, KbSpace, SpaceKind
from app.projects.access import (
    accessible_project_ids,
    can_manage_project,
    project_team_ids,
)
from app.teams.service import user_team_ids


async def ensure_spaces(db: AsyncSession) -> None:
    """Creates any missing org, team and project spaces. Idempotent."""
    await db.execute(
        text(
            "INSERT INTO kb_spaces (id, kind) SELECT gen_random_uuid(), 'org' "
            "WHERE NOT EXISTS (SELECT 1 FROM kb_spaces WHERE kind = 'org') ON CONFLICT DO NOTHING"
        )
    )
    await db.execute(
        text(
            "INSERT INTO kb_spaces (id, kind, team_id) SELECT gen_random_uuid(), 'team', t.id FROM teams t "
            "WHERE NOT EXISTS (SELECT 1 FROM kb_spaces s WHERE s.team_id = t.id) ON CONFLICT DO NOTHING"
        )
    )
    await db.execute(
        text(
            "INSERT INTO kb_spaces (id, kind, project_id) SELECT gen_random_uuid(), 'project', p.id FROM projects p "
            "WHERE NOT EXISTS (SELECT 1 FROM kb_spaces s WHERE s.project_id = p.id) ON CONFLICT DO NOTHING"
        )
    )


async def _get_or_create(db: AsyncSession, where, values: dict) -> KbSpace:
    space = (await db.execute(select(KbSpace).where(where))).scalar_one_or_none()
    if space is None:
        await db.execute(insert(KbSpace).values(id=uuid.uuid4(), **values).on_conflict_do_nothing())
        space = (await db.execute(select(KbSpace).where(where))).scalar_one()
    return space


async def org_space(db: AsyncSession) -> KbSpace:
    return await _get_or_create(db, KbSpace.kind == SpaceKind.org, {"kind": SpaceKind.org})


async def space_for_team(db: AsyncSession, team_id: uuid.UUID) -> KbSpace:
    return await _get_or_create(db, KbSpace.team_id == team_id, {"kind": SpaceKind.team, "team_id": team_id})


async def space_for_project(db: AsyncSession, project_id: uuid.UUID | str) -> KbSpace:
    pid = uuid.UUID(str(project_id))
    return await _get_or_create(db, KbSpace.project_id == pid, {"kind": SpaceKind.project, "project_id": pid})


async def readable_space_ids(db: AsyncSession, user: User) -> set[uuid.UUID]:
    stmt = select(KbSpace.id)
    if user.role != Role.admin:
        teams = await user_team_ids(db, user.id)
        projects = await accessible_project_ids(db, user) or set()
        stmt = stmt.where(
            or_(
                KbSpace.kind == SpaceKind.org,
                KbSpace.team_id.in_(teams),
                KbSpace.project_id.in_(projects),
            )
        )
    return set((await db.execute(stmt)).scalars())


async def can_read(db: AsyncSession, user: User, space: KbSpace) -> bool:
    if user.role == Role.admin or space.kind == SpaceKind.org:
        return True
    if space.kind == SpaceKind.team:
        return space.team_id in await user_team_ids(db, user.id)
    allowed = await accessible_project_ids(db, user)
    return allowed is None or space.project_id in allowed


async def can_write(db: AsyncSession, user: User, space: KbSpace) -> bool:
    return user.role != Role.viewer and await can_read(db, user, space)


async def can_manage_space(db: AsyncSession, user: User, space: KbSpace) -> bool:
    if user.role == Role.admin:
        return True
    if user.role != Role.manager:
        return False
    if space.kind == SpaceKind.team:
        return space.team_id in await user_team_ids(db, user.id)
    if space.kind == SpaceKind.project:
        return can_manage_project(user, await project_team_ids(db, space.project_id), await user_team_ids(db, user.id))
    return False


async def can_delete_document(db: AsyncSession, user: User, doc: KbDocument, space: KbSpace | None = None) -> bool:
    space = space or await db.get(KbSpace, doc.space_id)
    if space is None or not await can_write(db, user, space):
        return False
    return doc.created_by == user.id or await can_manage_space(db, user, space)


async def get_space_for(db: AsyncSession, user: User, space_id: uuid.UUID, write: bool = False) -> KbSpace:
    space = await db.get(KbSpace, space_id)
    if space is None or not await can_read(db, user, space):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "space_not_found")
    if write and user.role == Role.viewer:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    return space


async def get_document_for(
    db: AsyncSession, user: User, doc_id: uuid.UUID, write: bool = False
) -> tuple[KbDocument, KbSpace]:
    doc = await db.get(KbDocument, doc_id)
    space = await db.get(KbSpace, doc.space_id) if doc else None
    if doc is None or space is None or not await can_read(db, user, space):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document_not_found")
    if write and user.role == Role.viewer:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    return doc, space
