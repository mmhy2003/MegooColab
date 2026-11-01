import json
import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User
from app.core.crypto import decrypt, encrypt
from app.hub import rules
from app.hub.models import HubTool, HubToolFile, HubToolShare
from app.hub.schemas import (
    McpSpec,
    Named,
    SecretSlot,
    Sharing,
    ToolFileOut,
    ToolOut,
    ToolSummary,
)
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.teams.models import Team
from app.teams.service import user_team_ids


async def get_tool_or_404(db: AsyncSession, tool_id: uuid.UUID) -> HubTool:
    tool = await db.get(HubTool, tool_id)
    if tool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return tool


async def everyone_enabled(db: AsyncSession) -> bool:
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    return org is None or org.hub_share_everyone


async def shares_of(db: AsyncSession, tool: HubTool) -> list[HubToolShare]:
    return list((await db.execute(select(HubToolShare).where(HubToolShare.tool_id == tool.id))).scalars())


async def can_view(db: AsyncSession, user: User, tool: HubTool) -> bool:
    """The owner always; others while it is not removed and is shared with them (by their current teams)."""
    if tool.owner_id == user.id:
        return True
    if tool.removed_at is not None:
        return False
    shares = await shares_of(db, tool)
    teams = await user_team_ids(db, user.id)
    if any(s.user_id == user.id or s.team_id in teams for s in shares):
        return True
    if tool.share_everyone and await everyone_enabled(db):
        return True
    return user.role == Role.admin and (bool(shares) or tool.share_everyone)


async def sharing_of(db: AsyncSession, tool: HubTool) -> Sharing:
    shares = await shares_of(db, tool)
    team_ids = [s.team_id for s in shares if s.team_id]
    user_ids = [s.user_id for s in shares if s.user_id]
    teams = (await db.execute(select(Team).where(Team.id.in_(team_ids)).order_by(Team.name))).scalars()
    users = (await db.execute(select(User).where(User.id.in_(user_ids)).order_by(User.name))).scalars()
    return Sharing(
        teams=[Named(id=t.id, name=t.name) for t in teams],
        users=[Named(id=u.id, name=u.name) for u in users],
        everyone=tool.share_everyone,
    )


async def shelf(db: AsyncSession, user: User, which: str, q: str | None) -> list[HubTool]:
    stmt = select(HubTool).order_by(HubTool.name, HubTool.id)
    if which == "mine":
        stmt = stmt.where(HubTool.owner_id == user.id)
    else:
        stmt = stmt.where(HubTool.owner_id != user.id, HubTool.removed_at.is_(None))
        if which == "shared":
            teams = await user_team_ids(db, user.id)
            shared = select(HubToolShare.tool_id).where(
                or_(HubToolShare.user_id == user.id, HubToolShare.team_id.in_(teams))
            )
            stmt = stmt.where(HubTool.id.in_(shared))
        else:
            if not await everyone_enabled(db):
                return []
            stmt = stmt.where(HubTool.share_everyone.is_(True))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(HubTool.name.ilike(like), HubTool.description.ilike(like)))
    return list((await db.execute(stmt)).scalars())


async def visible_tool(db: AsyncSession, user: User, tool_id: uuid.UUID) -> HubTool:
    """The tool if the user may see it; a 404 otherwise, so a private tool's existence never shows."""
    tool = await get_tool_or_404(db, tool_id)
    if not await can_view(db, user, tool):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return tool


def require_owner(user: User, tool: HubTool) -> None:
    if tool.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")


def require_not_removed(tool: HubTool) -> None:
    if tool.removed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "hub_removed")


def bump(tool: HubTool, *, version: bool) -> None:
    """A change: rev always (machines go out of date), version when others would see it."""
    tool.rev += 1
    if version:
        tool.version += 1


def spec_of(tool: HubTool) -> McpSpec | None:
    return McpSpec.model_validate(tool.spec) if tool.spec is not None else None


def stored_spec(spec: McpSpec) -> dict:
    """The spec as kept in the database: secret values never stored there."""
    data = spec.model_dump(mode="json")
    for key in ("headers", "env"):
        for e in data[key]:
            if e["secret"]:
                e["value"] = ""
    return data


def read_secrets(tool: HubTool) -> dict[str, str]:
    """Internal only: the decrypted secret values. Never returned by any route of this module."""
    return json.loads(decrypt(tool.secrets_enc)) if tool.secrets_enc else {}


def write_secrets(tool: HubTool, values: dict[str, str]) -> None:
    kept = {k: v for k, v in values.items() if v}
    tool.secrets_enc = encrypt(json.dumps(kept)) if kept else None


def slots_of(tool: HubTool) -> list[str]:
    spec = spec_of(tool)
    return rules.secret_slots(spec) if spec else []


def set_spec(tool: HubTool, spec: McpSpec) -> None:
    """Replaces the setup; values of secret slots that no longer exist are dropped."""
    tool.spec = stored_spec(spec)
    slots = set(rules.secret_slots(spec))
    write_secrets(tool, {k: v for k, v in read_secrets(tool).items() if k in slots})


async def replace_files(db: AsyncSession, tool: HubTool, files: list[tuple[str, bytes]]) -> None:
    await db.execute(delete(HubToolFile).where(HubToolFile.tool_id == tool.id))
    db.add_all(HubToolFile(tool_id=tool.id, path=p, content=data, size=len(data)) for p, data in files)
    await db.flush()


async def _files(db: AsyncSession, tool: HubTool) -> list[HubToolFile]:
    rows = (await db.execute(select(HubToolFile).where(HubToolFile.tool_id == tool.id))).scalars()
    return sorted(rows, key=lambda f: f.path)  # by code point, whatever the database's collation


async def summary(db: AsyncSession, user: User, tool: HubTool) -> ToolSummary:
    owner = await db.get(User, tool.owner_id)
    mine = tool.owner_id == user.id
    secrets = read_secrets(tool) if mine else {}
    runs_code = tool.kind == "skill" and any(
        rules.script_systems(f.path) for f in await _files(db, tool)
    )
    return ToolSummary(
        id=tool.id,
        kind=tool.kind,
        name=tool.name,
        description=tool.description,
        version=tool.version,
        rev=tool.rev,
        owner=Named(id=owner.id, name=owner.name),
        is_copy=tool.is_copy,
        removed=tool.removed_at is not None,
        secrets_missing=mine and any(s not in secrets for s in slots_of(tool)),
        runs_code=runs_code,
        read_only_safe=tool.read_only_safe,
        sharing=await sharing_of(db, tool) if mine else None,
    )


async def tool_out(db: AsyncSession, user: User, tool: HubTool) -> ToolOut:
    base = await summary(db, user, tool)
    mine = tool.owner_id == user.id
    secrets = read_secrets(tool) if mine else {}
    spec = spec_of(tool)
    files = None
    if tool.kind == "skill":
        files = [ToolFileOut(path=f.path, size=f.size, runs_on=rules.script_systems(f.path)) for f in await _files(db, tool)]
    return ToolOut(
        **base.model_dump(),
        spec=spec,
        secrets=[SecretSlot(name=s, set=s in secrets) for s in slots_of(tool)],
        files=files,
        flagged=rules.flagged_values(spec) if spec else [],
        can_edit=mine and not tool.is_copy and tool.removed_at is None,
    )
