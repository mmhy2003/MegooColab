import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AuthedUser
from app.core.db import DbSession
from app.hub import service
from app.hub.models import HubTool
from app.hub.schemas import SecretsIn, ToolIn, ToolOut, ToolPatch

router = APIRouter(prefix="/api/hub", tags=["hub"])


async def _flush_unique_name(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "hub_name_taken")


async def _own(db: AsyncSession, user, tool_id: uuid.UUID) -> HubTool:
    tool = await service.visible_tool(db, user, tool_id)
    service.require_owner(user, tool)
    return tool


@router.post("/tools", status_code=status.HTTP_201_CREATED)
async def create_tool(body: ToolIn, user: AuthedUser, db: DbSession) -> ToolOut:
    tool = HubTool(owner_id=user.id, kind=body.kind, name=body.name, description=body.description,
                   read_only_safe=body.read_only_safe)
    service.set_spec(tool, body.spec)
    db.add(tool)
    await _flush_unique_name(db)
    return await service.tool_out(db, user, tool)


@router.get("/tools/{tool_id}")
async def get_tool(tool_id: uuid.UUID, user: AuthedUser, db: DbSession) -> ToolOut:
    return await service.tool_out(db, user, await service.visible_tool(db, user, tool_id))


@router.patch("/tools/{tool_id}")
async def patch_tool(tool_id: uuid.UUID, body: ToolPatch, user: AuthedUser, db: DbSession) -> ToolOut:
    tool = await _own(db, user, tool_id)
    service.require_not_removed(tool)
    fields = body.model_fields_set
    if tool.is_copy and fields - {"read_only_safe"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "hub_copy_read_only")
    visible = False
    if body.name is not None and body.name != tool.name:
        tool.name, visible = body.name, True
    if body.description is not None and body.description != tool.description:
        tool.description, visible = body.description, True
    if body.spec is not None and tool.kind == "mcp":
        before = tool.spec
        service.set_spec(tool, body.spec)
        visible = visible or tool.spec != before
    changed = visible
    if body.read_only_safe is not None and body.read_only_safe != tool.read_only_safe:
        tool.read_only_safe, changed = body.read_only_safe, True
    if changed:
        service.bump(tool, version=visible)
    await _flush_unique_name(db)
    return await service.tool_out(db, user, tool)


@router.put("/tools/{tool_id}/secrets")
async def put_secrets(tool_id: uuid.UUID, body: SecretsIn, user: AuthedUser, db: DbSession) -> ToolOut:
    tool = await _own(db, user, tool_id)
    service.require_not_removed(tool)
    slots = set(service.slots_of(tool))
    if set(body.values) - slots:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "hub_unknown_secret")
    current = service.read_secrets(tool)
    service.write_secrets(tool, current | body.values)
    service.bump(tool, version=False)
    await db.flush()
    return await service.tool_out(db, user, tool)


@router.delete("/tools/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(tool_id: uuid.UUID, user: AuthedUser, db: DbSession) -> Response:
    tool = await _own(db, user, tool_id)
    await db.delete(tool)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
