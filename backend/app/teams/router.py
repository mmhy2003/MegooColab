import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.agents.service import agents_out
from app.audit import service as audit
from app.auth.deps import AuthedUser
from app.auth.models import Role, User
from app.auth.schemas import UserOut
from app.core.db import DbSession
from app.core.events import Event, publish
from app.kb import access as kb_access
from app.memory import entities as mem_entities
from app.memory.models import EntityKind
from app.teams import service
from app.teams.models import Team, TeamMember
from app.teams.schemas import (
    MembersIn,
    TeamDetail,
    TeamIn,
    TeamOut,
    TeamPatch,
    TeamSummary,
)

router = APIRouter(prefix="/api/teams", tags=["teams"])


async def _flush_unique_name(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "team_name_taken")


async def _detail(db: AsyncSession, team: Team, viewer: User) -> TeamDetail:
    members = list(
        (
            await db.execute(
                select(User).join(TeamMember, TeamMember.user_id == User.id)
                .where(TeamMember.team_id == team.id).order_by(User.name)
            )
        ).scalars()
    )
    agents = (
        await db.execute(
            select(Agent).where(Agent.owner_id.in_([u.id for u in members])).order_by(Agent.name)
        )
    ).scalars()
    return TeamDetail(
        id=team.id,
        name=team.name,
        description=team.description,
        members=[UserOut.model_validate(u) for u in members],
        projects=await _visible_projects(db, team, viewer),
        project_count=(await service.team_project_counts(db, [team.id])).get(team.id, 0),
        blocking_project_count=await service.blocking_project_count(db, team.id),
        agents=await agents_out(db, list(agents), viewer),
    )


async def _visible_projects(db: AsyncSession, team: Team, viewer: User) -> list[dict]:
    from app.projects.access import accessible_project_ids

    allowed = await accessible_project_ids(db, viewer)
    return [p for p in await service.team_projects(db, team.id) if allowed is None or p["id"] in allowed]


@router.get("")
async def list_teams(user: AuthedUser, db: DbSession) -> list[TeamSummary]:
    member_counts = (
        select(TeamMember.team_id, func.count().label("n")).group_by(TeamMember.team_id).subquery()
    )
    rows = await db.execute(
        select(Team, func.coalesce(member_counts.c.n, 0))
        .outerjoin(member_counts, member_counts.c.team_id == Team.id)
        .order_by(Team.name)
    )
    project_counts = await service.team_project_counts(db)
    mine = await service.user_team_ids(db, user.id)
    return [
        TeamSummary(
            id=t.id, name=t.name, description=t.description,
            member_count=n, project_count=project_counts.get(t.id, 0), is_member=t.id in mine,
        )
        for t, n in rows
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_team(body: TeamIn, user: AuthedUser, db: DbSession) -> TeamOut:
    if user.role not in (Role.admin, Role.manager):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    team = Team(name=body.name, description=body.description)
    db.add(team)
    await _flush_unique_name(db)
    if user.role == Role.manager:
        db.add(TeamMember(team_id=team.id, user_id=user.id))
    await kb_access.space_for_team(db, team.id)
    await mem_entities.ensure_entity(db, EntityKind.team, team.id)
    await audit.record(db, "team.created", actor_id=user.id, target_type="team", target_id=team.id)
    return TeamOut.model_validate(team)


@router.get("/{team_id}")
async def get_team(team_id: uuid.UUID, user: AuthedUser, db: DbSession) -> TeamDetail:
    return await _detail(db, await service.get_team_or_404(db, team_id), user)


@router.patch("/{team_id}")
async def update_team(team_id: uuid.UUID, body: TeamPatch, user: AuthedUser, db: DbSession) -> TeamOut:
    team = await service.get_team_or_404(db, team_id)
    await service.require_team_manage(db, user, team)
    if body.name is not None:
        team.name = body.name
    if body.description is not None:
        team.description = body.description
    await _flush_unique_name(db)
    return TeamOut.model_validate(team)


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(team_id: uuid.UUID, user: AuthedUser, db: DbSession) -> None:
    team = await service.get_team_or_404(db, team_id)
    await service.require_team_manage(db, user, team)
    if await service.blocking_project_count(db, team.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "team_has_projects")
    from app.projects.models import ProjectTeam  # local: the projects modules import teams

    # archived projects let the team go: an admin gives one teams again when restoring it
    released = [p["id"] for p in await service.team_projects(db, team.id)]
    await db.execute(delete(ProjectTeam).where(ProjectTeam.team_id == team.id))
    removed = await service.team_member_ids(db, team.id)
    await db.delete(team)
    await audit.record(db, "team.deleted", actor_id=user.id, target_type="team", target_id=team.id,
                       data={"archived_projects_released": [str(p) for p in released]} if released else None)
    for uid in removed:
        await publish(db, Event(type="membership.changed", user_id=uid))


@router.put("/{team_id}/members")
async def replace_members(team_id: uuid.UUID, body: MembersIn, user: AuthedUser, db: DbSession) -> TeamDetail:
    team = await service.get_team_or_404(db, team_id)
    await service.require_team_manage(db, user, team)
    wanted = set(body.user_ids)
    if wanted:
        found = set((await db.execute(select(User.id).where(User.id.in_(wanted)))).scalars())
        if found != wanted:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_user")
    current = await service.team_member_ids(db, team.id)
    removed, added = current - wanted, wanted - current
    if removed:
        await db.execute(
            delete(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id.in_(removed))
        )
    for uid in added:
        db.add(TeamMember(team_id=team.id, user_id=uid))
    await db.flush()
    if added or removed:
        await audit.record(
            db, "team.members_changed", actor_id=user.id, target_type="team", target_id=team.id,
            data={"added": [str(u) for u in added], "removed": [str(u) for u in removed]},
        )
    for uid in added | removed:
        await publish(db, Event(type="membership.changed", user_id=uid))
    return await _detail(db, team, user)
