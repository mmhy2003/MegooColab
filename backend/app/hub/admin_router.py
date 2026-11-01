"""Admins and the Tool Hub: every tool shared beyond its owner, and stopping or removing one. Never secrets."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.auth.deps import AdminUser
from app.core.db import DbSession
from app.hub import service
from app.hub.models import HubTool, HubToolShare
from app.hub.schemas import AdminToolOut

admin_router = APIRouter(prefix="/api/admin/hub", tags=["admin"])


def _shared():
    return or_(HubTool.share_everyone.is_(True), HubTool.id.in_(select(HubToolShare.tool_id)))


async def _shared_tool(db: AsyncSession, tool_id: uuid.UUID) -> HubTool:
    tool = await service.get_tool_or_404(db, tool_id)
    shared = tool.share_everyone or bool(await service.shares_of(db, tool))
    if tool.removed_at is not None or not shared:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return tool


async def _unshare(db: AsyncSession, tool: HubTool) -> None:
    await db.execute(delete(HubToolShare).where(HubToolShare.tool_id == tool.id))
    tool.share_everyone = False


@admin_router.get("/tools")
async def list_shared(admin: AdminUser, db: DbSession, q: str | None = None) -> list[AdminToolOut]:
    stmt = select(HubTool).where(HubTool.removed_at.is_(None), _shared()).order_by(HubTool.name, HubTool.id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(HubTool.name.ilike(like), HubTool.description.ilike(like)))
    out = []
    for tool in (await db.execute(stmt)).scalars():
        base = await service.summary(db, admin, tool)
        out.append(AdminToolOut(**base.model_dump(exclude={"sharing"}), sharing=await service.sharing_of(db, tool)))
    return out


@admin_router.post("/tools/{tool_id}/unshare", status_code=status.HTTP_204_NO_CONTENT)
async def unshare(tool_id: uuid.UUID, admin: AdminUser, db: DbSession) -> Response:
    tool = await _shared_tool(db, tool_id)
    await _unshare(db, tool)
    await audit.record(db, "hub.tool_unshared", actor_id=admin.id, target_type="hub_tool", target_id=tool.id,
                       data={"name": tool.name})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.post("/tools/{tool_id}/remove", status_code=status.HTTP_204_NO_CONTENT)
async def remove(tool_id: uuid.UUID, admin: AdminUser, db: DbSession) -> Response:
    """Takes the tool off every shelf and marks it and its live copies removed; machines change only on a push."""
    tool = await _shared_tool(db, tool_id)
    await _unshare(db, tool)
    now = datetime.now(UTC)
    copies = (
        await db.execute(select(HubTool).where(HubTool.source_id == tool.id, HubTool.is_copy.is_(True)))
    ).scalars()
    for t in [tool, *copies]:
        t.removed_at, t.removed_by_id = now, admin.id
        t.rev += 1
    await audit.record(db, "hub.tool_removed", actor_id=admin.id, target_type="hub_tool", target_id=tool.id,
                       data={"name": tool.name})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
