import io
import uuid
import zipfile
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AuthedUser
from app.core.db import DbSession
from app.hub import rules, service
from app.hub.models import HubTool, HubToolFile
from app.hub.schemas import SecretsIn, ToolFileText, ToolIn, ToolOut, ToolPatch

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


# a zip can be at most this big on the wire; what it unpacks to is checked against rules.MAX_SKILL_BYTES
_MAX_UPLOAD = 2 * rules.MAX_SKILL_BYTES


async def _read_capped(f: UploadFile, cap: int) -> bytes:
    data = await f.read(cap + 1)
    if len(data) > cap:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "hub_skill_too_large")
    return data


async def _skill_files(file: UploadFile | None, files: list[UploadFile] | None) -> list[tuple[str, bytes]]:
    """A skill's files from one .zip or from a folder's files (each named by its relative path)."""
    if file is not None:
        raw = await _read_capped(file, _MAX_UPLOAD)
        try:
            z = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "hub_bad_zip")
        infos = [i for i in z.infolist() if not i.is_dir()]
        # the sizes the zip declares, before anything is unpacked
        if len(infos) > rules.MAX_SKILL_FILES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "hub_too_many_files")
        if any(i.file_size > rules.MAX_SKILL_FILE_BYTES for i in infos) or sum(
            i.file_size for i in infos
        ) > rules.MAX_SKILL_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "hub_skill_too_large")
        entries = []
        for i in infos:
            with z.open(i) as fh:
                data = fh.read(rules.MAX_SKILL_FILE_BYTES + 1)
            entries.append((i.filename, data))
    else:
        if not files:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "hub_skill_no_skill_md")
        if len(files) > rules.MAX_SKILL_FILES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "hub_too_many_files")
        entries = [(f.filename or "", await _read_capped(f, rules.MAX_SKILL_FILE_BYTES)) for f in files]
    return rules.normalize_skill_files(entries)


def _frontmatter(files: list[tuple[str, bytes]]) -> tuple[str | None, str | None]:
    md = next(data for path, data in files if path == "SKILL.md")
    return rules.skill_frontmatter(md.decode("utf-8", errors="replace"))


@router.post("/skills", status_code=status.HTTP_201_CREATED)
async def create_skill(
    user: AuthedUser,
    db: DbSession,
    file: Annotated[UploadFile | None, File()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> ToolOut:
    entries = await _skill_files(file, files)
    name, description = _frontmatter(entries)
    if not name or not rules.NAME_RE.fullmatch(name):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "hub_bad_name")
    tool = HubTool(owner_id=user.id, kind="skill", name=name, description=(description or "")[:2000])
    db.add(tool)
    await _flush_unique_name(db)
    await service.replace_files(db, tool, entries)
    return await service.tool_out(db, user, tool)


@router.put("/tools/{tool_id}/files")
async def put_files(
    tool_id: uuid.UUID,
    user: AuthedUser,
    db: DbSession,
    file: Annotated[UploadFile | None, File()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> ToolOut:
    tool = await _own(db, user, tool_id)
    service.require_not_removed(tool)
    if tool.is_copy:
        raise HTTPException(status.HTTP_409_CONFLICT, "hub_copy_read_only")
    if tool.kind != "skill":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "hub_not_a_skill")
    entries = await _skill_files(file, files)
    _, description = _frontmatter(entries)
    if description is not None:
        tool.description = description[:2000]
    await service.replace_files(db, tool, entries)
    service.bump(tool, version=True)
    await db.flush()
    return await service.tool_out(db, user, tool)


@router.get("/tools/{tool_id}/file")
async def read_file(tool_id: uuid.UUID, path: str, user: AuthedUser, db: DbSession) -> ToolFileText:
    tool = await service.visible_tool(db, user, tool_id)
    f = (
        await db.execute(select(HubToolFile).where(HubToolFile.tool_id == tool.id, HubToolFile.path == path))
    ).scalar_one_or_none()
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    try:
        text = f.content.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    return ToolFileText(path=f.path, size=f.size, text=text)
